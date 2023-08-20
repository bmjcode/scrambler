#!/usr/bin/env python3

"""The Scrambler is a CGI script that turns webpages to gibberish.

Specify the page to scramble using the "url" parameter in the
query string, like so:
/cgi-bin/scrambler.py?url=https%3A//en.wikipedia.org/wiki/Main_Page

Browsing is restricted to the host domain and others listed in the
SCRAMBLER_ALLOWLIST environment variable (comma-separated).

You can also use the Scrambler as a honeypot by adding "&honeypot=1"
to the query string. This is intended to annoy unwelcome scrapers.
In honeypot mode, browsing is restricted to your own domain, and
access to content the Scrambler can't process is blocked. Redirecting
scrapers through the Scrambler is left as an exercise to the reader.
"""

# Copyright (c) 2023 Benjamin Johnson <bmjcode@gmail.com>
# 
# Permission to use, copy, modify, and distribute this software for any
# purpose with or without fee is hereby granted, provided that the above
# copyright notice and this permission notice appear in all copies.
# 
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
# WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
# ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
# WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
# ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
# OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

import os
import sys
import cgi

import codecs
import gzip
import html
import random
import ssl
import unicodedata

from html.parser import HTMLParser
from urllib.parse import quote, urljoin, urlparse
from urllib.request import urlopen
from urllib.error import HTTPError

# This is from the request header and required by the HTTP 1.1 spec
HTTP_HOST = os.getenv("HTTP_HOST", "localhost")

# These are required by the CGI spec so we should never fall back
# on the default values
SCRIPT_NAME = os.getenv("SCRIPT_NAME", "scrambler.py")
SERVER_PORT = int(os.getenv("SERVER_PORT", 8000))
SERVER_SOFTWARE = os.getenv("SERVER_SOFTWARE", "")

# Domains we are allowed to browse
ALLOWED_DOMAINS = [
    HTTP_HOST,
    *map(str.strip, os.getenv("SCRAMBLER_ALLOWLIST", "").split(","))
]

# Block JavaScript on scrambled pages?
SUPPRESS_SCRIPTS = True

# Default URL for the Scrambler
if SERVER_SOFTWARE.startswith("SimpleHTTP/"):
    # Sanity check for running under `py -m http.server`.
    # SimpleHTTP only supports a single connection at a time,
    # so connecting to localhost will cause an infinite loop.
    # The choice of Wikipedia as an alternative is arbitrary.
    DEFAULT_URL = "https://en.wikipedia.org/wiki/Main_Page"
else:
    DEFAULT_URL = "{0}://{1}{2}/".format(
        "https" if SERVER_PORT == 443 else "http",
        HTTP_HOST,
        "" if SERVER_PORT in (80, 443) else ":{0}".format(SERVER_PORT),
    )


class Scrambler(object):
    """Text scrambler.

    This turns text into gibberish by randomly rearranging letters
    and numbers while preserving the original spaces and punctuation.

    If constructed with preserve_letter_distribution == True, the
    scrambled text will maintain the original distribution of consonants
    and vowels. Otherwise, they will be mixed freely.
    """

    __slots__ = ["_buf", "_alpha", "_cons", "_vowels", "_digits",
                 "_preserve_letter_distribution"]

    def __init__(self, preserve_letter_distribution=True):
        """Initialize the text scrambler."""

        # Buffer holding the content to scramble
        self._buf = []

        # Alphabetic characters in the original content
        self._alpha = []

        # Consonants in the original content
        self._cons = []

        # Vowels in the original content
        self._vowels = []

        # List of numbers (as str values) in the original content
        self._digits = []

        # Preserve the original distribution of consonants and vowels?
        self._preserve_letter_distribution = preserve_letter_distribution

    def clear(self):
        """Clear the scrambler buffer."""

        del self._buf[:]
        del self._alpha[:]
        del self._cons[:]
        del self._vowels[:]
        del self._digits[:]

    def feed(self, text):
        """Feed content to the scrambler."""

        for c in text:
            self._buf.append(c)

            if c.isalpha():
                c = c.lower()
                if self._preserve_letter_distribution:
                    # Strip accents, diacritics, etc.
                    n = unicodedata.normalize("NFKD", c)[0]
                    if n in self._CONSONANTS:
                        self._cons.append(c)
                    elif n in self._VOWELS:
                        self._vowels.append(c)
                    else:
                        self._alpha.append(c)
                else:
                    self._alpha.append(c)

            elif c.isdigit():
                self._digits.append(c)

    def flush(self):
        """Return the content of, then clear, the buffer."""

        text = []
        for i, c in enumerate(self._buf):
            if c.isalpha():
                # Select a random letter in the same case as the original
                if c.isupper():
                    text.append(self._pop_letter(c).upper())
                else:
                    text.append(self._pop_letter(c))

            elif c.isdigit():
                # Select a random digit
                text.append(self._digits.pop(0))

            else:
                # Preserve non-alphanumeric characters
                text.append(c)

        self.clear()
        return "".join(text)

    def scramble(self):
        """Scramble content and clear the buffer."""

        r = random.SystemRandom()
        r.seed()

        # Shuffle our letters and numbers
        r.shuffle(self._alpha)
        if self._preserve_letter_distribution:
            r.shuffle(self._cons)
            r.shuffle(self._vowels)
        r.shuffle(self._digits)

        return self.flush()

    def _pop_letter(self, c=None):
        """Return a random consonant or vowel, depending on which 'c' is.

        The caller should first ensure that c.isalpha() == True.
        """

        try:
            if c and self._preserve_letter_distribution:
                # Strip accents, diacritics, etc.
                n = unicodedata.normalize("NFKD", c)[0]
                if n.lower() in self._CONSONANTS:
                    return self._cons.pop(0)
                elif n.lower() in self._VOWELS:
                    return self._vowels.pop(0)
                else:
                    return self._alpha.pop(0)
            else:
                return self._alpha.pop(0)

        except (IndexError):
            # This should never happen
            return ""

    # These are used when preserve_letter_distribution is on
    _CONSONANTS = "bcdfghjklmnpqrstvwxz"
    _VOWELS = "aeiouy"


class HTMLScrambler(HTMLParser):
    """Class to scramble text in HTML content.

    If the source_ and target_encoding parameters are specified,
    characters in the content that the target encoding can't
    natively represent will be escaped with entity references.
    Beware that this does NOT change the actual encoding of the
    scrambler's output, only the representation of those specific
    characters. Since characters in comments, script and style
    blocks, etc. cannot be escaped as entity references, you will
    still need to handle those yourself if the source and target
    encodings differ. You are not expected to understand this.

    If suppress_scripts is enabled, all JavaScript will be removed
    from the scrambled page. This is on by default for security.
    """

    # This is based heavily on pywebarchive's HTMLRewriter. See:
    # https://github.com/bmjcode/pywebarchive/blob/master/webarchive/util.py

    __slots__ = ["_base_url", "_is_honeypot",
                 "_source_encoding", "_target_encoding", "_suppress_scripts",
                 "_buf", "_html", "_is_scrambling", "_is_xhtml", "_is_script"]

    def __init__(self, base_url, is_honeypot=False, *,
                 source_encoding=None,
                 target_encoding=None,
                 suppress_scripts=True):
        """Initialize the HTML scrambler."""

        HTMLParser.__init__(self, convert_charrefs=False)

        # URL of the original page to scramble
        self._base_url = base_url

        # Is this a honeypot? (restricts access to external sites)
        self._is_honeypot = is_honeypot

        # Text encoding of the original page
        self._source_encoding = source_encoding

        # Text encoding of our output stream
        self._target_encoding = target_encoding

        # Remove JavaScript from the output? (always on in honeypot mode)
        self._suppress_scripts = suppress_scripts or self._is_honeypot

        # Buffer for content to scramble
        # The special value "<>" indicates the position of HTML code
        self._buf = []

        # HTML code (tags, entities, script and style data, etc.)
        # This obviously must stay unscrambled for the page to display
        self._html = []

        # Set this to False to temporarily disable scrambling
        self._is_scrambling = True

        # Are we inside a script block? (only used if suppress_scripts is on)
        self._is_script = False

        # Is this page XHTML? (used to add /> to self-closing tags)
        self._is_xhtml = False

    def handle_starttag(self, tag, attrs):
        """Handle a start tag."""

        if tag == "script":
            self._is_script = True
            if self._suppress_scripts:
                return

        elif tag in self._DONT_SCRAMBLE:
            # Temporarily deactivate scrambling
            self._is_scrambling = False

        self._html.append(self._build_starttag(tag, attrs))
        self._buf.append("<>")

    def handle_startendtag(self, tag, attrs):
        """Handle an XHTML-style "empty" start tag."""

        if tag == "script" and self._suppress_scripts:
            # We should never see this since <script /> is invalid HTML
            return

        self._html.append(self._build_starttag(tag, attrs, True))
        self._buf.append("<>")

    def handle_endtag(self, tag):
        """Handle an end tag."""

        if tag == "script":
            self._is_script = False
            if self._suppress_scripts:
                return

        elif tag in self._DONT_SCRAMBLE:
            # Reactivate scrambling
            self._is_scrambling = True

        self._html.append("</{0}>".format(tag))
        self._buf.append("<>")

    def handle_data(self, data):
        """Handle arbitrary data."""

        if self._is_script and self._suppress_scripts:
            self._html.append("<!-- script removed -->")
            self._buf.append("<>")

        elif self._is_scrambling:
            self._buf.append(data)

        else:
            self._html.append(data)
            self._buf.append("<>")

    def handle_entityref(self, name):
        """Handle a named character reference."""

        self._html.append("&{0};".format(name))
        self._buf.append("<>")

    def handle_charref(self, name):
        """Handle a numeric character reference."""

        self._html.append("&#{0};".format(name))
        self._buf.append("<>")

    def handle_comment(self, data):
        """Handle a comment."""

        # Note IE conditional comments potentially can affect rendering
        self._html.append("<!--{0}-->".format(data))
        self._buf.append("<>")

    def handle_decl(self, decl):
        """Handle a doctype declaration."""

        self._html.append("<!{0}>".format(decl))
        self._buf.append("<>")

        # This catches XHTML documents incorrectly served with an HTML type
        if "//DTD XHTML " in decl:
            self._is_xhtml = True

    def scramble(self):
        """Scramble content."""

        text = []
        scrambler = Scrambler()
        scrambler.feed("".join(self._buf))

        for chunk in scrambler.scramble().split("<>"):
            if self._source_encoding and self._target_encoding:
                # Convert content characters that the target encoding
                # can't natively represent to entity references. We
                # convert back to the source encoding afterwards because
                # the user is still responsible for handling characters
                # that can't be escaped this way; see the class docstring.
                text.append(chunk
                            .encode(self._target_encoding, "xmlcharrefreplace")
                            .decode(self._source_encoding, "ignore"))
            else:
                text.append(chunk)

            if self._html:
                text.append(self._html.pop(0))

        return "".join(text)

    def _build_starttag(self, tag, attrs, is_empty=False):
        """Build an HTML start tag."""

        # Open the tag
        tag_data = ["<", tag]

        # Process attributes
        for attr, value in attrs:
            tag_data.append(" ")
            tag_data.append(attr)
            if value or value == "":
                # The weird check is to catch empty string values as opposed
                # to actually valueless attributes like iframe's "seamless"
                tag_data.append('="')
                tag_data.append(self._process_attr_value(tag, attr, value))
                tag_data.append('"')
            elif self._is_xhtml:
                # XHTML requires all attributes to have a value
                tag_data.append('="')
                tag_data.append(attr)
                tag_data.append('"')

        # Disable form fields
        if tag == "input":
            tag_data.append(" disabled")
            if self._is_xhtml:
                tag_data.append('="disabled"')

        # Close the tag
        if self._is_xhtml and (is_empty or tag in self._VOID_ELEMENTS):
            tag_data.append(" />")
        else:
            tag_data.append(">")

        return "".join(tag_data)

    def _process_attr_value(self, tag, attr, value):
        """Process the value of a tag's attribute."""

        if ((tag == "a" and attr == "href")
            or (tag in ("frame", "iframe") and attr == "src")):
            # Scramble hyperlink and frame targets
            target = quote(urljoin(self._base_url, value))
            if self._is_honeypot:
                # Keep outgoing links within the honeypot
                value = "".join(("?honeypot=1&url=", target))
            else:
                value = "".join(("?url=", target))

        elif attr in ("action", "href", "src"):
            # Pass through the original versions of anything we can't scramble
            value = urljoin(self._base_url, value)

        elif attr == "srcset":
            srcset = []
            for item in map(str.strip, value.split(",")):
                if " " in item:
                    # Source-size pair, like "image.png 2x"
                    src, size = item.split(" ", 1)
                    src = urljoin(self._base_url, src)
                    srcset.append("{0} {1}".format(src, size))
                else:
                    # Source only -- no size specified
                    srcset.append(urljoin(self._base_url, item))

            value = ", ".join(srcset)

        elif attr in ("alt", "placeholder", "title", "value"):
            scrambler = Scrambler()
            scrambler.feed(value)
            value = scrambler.scramble()

        return html.escape(value, True)

    # Tags containing raw data we shouldn't scramble
    _DONT_SCRAMBLE = ("script", "style")

    # Valid self-closing tags (formally termed "void elements") in HTML
    # See: http://xahlee.info/js/html5_non-closing_tag.html
    #
    # Python's HTMLParser is supposed to call handle_startendtag() when it
    # encounters such a tag, but in practice this does not always happen.
    # We thus check against this list of known self-closing tags to ensure
    # these are correctly closed when processing XHTML documents.
    _VOID_ELEMENTS = (
        "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr",
        # Obsolete tags
        "command", "keygen", "menuitem"
    )


def _scrambler_error(code, message):
    """Display an error message."""

    print("Status: {0}".format(code))
    print("Content-type: text/plain")
    print()
    print(message)


def scramble(url, is_honeypot=False):
    """Scramble the webpage at the specified URL."""

    context = ssl.create_default_context()

    with urlopen(url, context=context) as src:
        scrambler = None
        charset = src.headers.get_content_charset() or "utf-8"

        # Note the Content-Type header may also include the character encoding
        content_type = src.info().get("Content-Type")
        mime_type = content_type.split(";")[0]
        if mime_type in ("text/html", "application/xhtml+xml"):
            # Scramble HTML
            scrambler = HTMLScrambler(url, is_honeypot,
                                      source_encoding=charset,
                                      target_encoding=sys.stdout.encoding,
                                      suppress_scripts=SUPPRESS_SCRIPTS)
        elif (content_type.startswith("text/")):
            # Scramble plain text
            scrambler = Scrambler()

        if scrambler:
            # Decompress gzip'd content if needed
            if src.info().get("Content-Encoding") == "gzip":
                content = gzip.decompress(src.read())
            else:
                content = src.read()

            # Convert the content from bytes to an appropriately encoded str
            content = content.decode(charset)

            # Scramble the page!
            scrambler.feed(content)
            print("Content-Type: {0}; charset={1}"
                  .format(mime_type, sys.stdout.encoding))
            print()
            print(scrambler.scramble()
                  .encode(charset, "ignore")
                  .decode(sys.stdout.encoding, "ignore"))

        else:
            # We can't scramble this type
            if is_honeypot:
                # Block access to the file
                _scrambler_error(403,
                    "Access to this file has been blocked.")
            else:
                # Redirect to the unscrambled file
                print("Status: 303")
                print("Location: {0}".format(url))
                print()


def main():
    form = cgi.FieldStorage()

    # URL of the page to scramble
    url = form.getfirst("url", DEFAULT_URL)
    if not "://" in url:
        # Interpret this as a relative URL
        url = urljoin(DEFAULT_URL, url)

    try:
        parsed_url = urlparse(url)
    except (ValueError) as e:
        _scrambler_error(500, str(e))
        return

    # Sanity checks
    if parsed_url.hostname == HTTP_HOST and parsed_url.path == SCRIPT_NAME:
        # Prevent an infinite loop
        _scrambler_error(403,
            "Sorry, the Scrambler cannot scramble itself.")
    elif parsed_url.scheme not in ("http", "https"):
        # Restrict available protocols to HTTP and HTTPS
        _scrambler_error(500,
            "Unsupported URL scheme: '{0}'"
            .format(parsed_url.scheme))
        return
    elif not (parsed_url.port is None
              or (parsed_url.scheme == "http" and parsed_url.port == 80)
              or (parsed_url.scheme == "https" and parsed_url.port == 443)):
        # Restrict traffic to well-known ports
        _scrambler_error(500,
            "Invalid port for URL scheme '{0}': {1}"
            .format(parsed_url.scheme, parsed_url.port))
        return

    allowed_url = False
    is_honeypot = bool(form.getfirst("honeypot", False))
    if url == DEFAULT_URL:
        # Always allow our default URL
        allowed_url = True
    elif is_honeypot:
        # Restrict traffic to the host domain
        allowed_url = (parsed_url.hostname == HTTP_HOST)
    else:
        # Check URLs against the allowlist
        allowed_url = (parsed_url.hostname in ALLOWED_DOMAINS)

    if allowed_url:
        try:
            scramble(url, is_honeypot)
        except (HTTPError) as e:
            _scrambler_error(e.code,
                "{0} {1}"
                .format(e.code, e.reason))
    else:
        _scrambler_error(403,
            "Sorry, {0} is not on the Scrambler's allowlist."
            .format(parsed_url.hostname))


if __name__ == "__main__":
    main()
