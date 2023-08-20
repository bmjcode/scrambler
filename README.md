The Scrambler turns your website to gibberish to confuse humans and annoy scrapers.

I made the Scrambler as a creative response to [rampant scraping](https://www.nytimes.com/2023/07/15/technology/artificial-intelligence-models-chat-data.html) by [AI companies](https://arstechnica.com/information-technology/2023/08/openai-details-how-to-keep-chatgpt-from-gobbling-up-website-data/), who [for years](https://www.bbc.com/news/technology-51220654) have [collected our data](https://www.theregister.com/2023/07/06/google_ai_models_internet_scraping/) with [neither consent nor payment](https://www.tomshardware.com/news/google-ai-scraping-as-fair-use) to [train their models](https://arstechnica.com/information-technology/2023/07/book-authors-sue-openai-and-meta-over-text-used-to-train-ai/) -- often for purposes that [directly harm us](https://www.businessinsider.com/openai-gptbot-web-crawler-content-creators-ai-bots-2023-8?op=1). Think of it as a less polite alternative to [robots.txt](https://en.wikipedia.org/wiki/Robots.txt). I am not the first to think of [this idea](https://arstechnica.com/information-technology/2023/08/openai-details-how-to-keep-chatgpt-from-gobbling-up-website-data/?comments=1&post=42102431), but I like to think having multiple people's takes on it can only make the world a better place.


## Installation

The Scrambler is a CGI script written in Python 3. It uses no modules outside the standard library. Place [scrambler.py](scrambler.py) in your server's `cgi-bin` directory and make it executable. Congratulations, you're now ready for visitors.

To scramble a webpage, pass its URL through the [query string](https://en.wikipedia.org/wiki/Query_string), like so: `?url=https%3A//www.example.com` (`%3A` is the escape code for the `':'` character). If you do not specify a URL, the Scrambler defaults to the root page of your domain.

To prevent abuse, the Scrambler is restricted by default to browsing its host domain. You can allow access to additional sites by setting the `SCRAMBLER_ALLOWLIST` environment variable to a comma-separated list of domains. Note that the domain must *exactly* match your allowlist -- `example.com` and `www.example.com` would be considered separate sites. Other precautions the Scrambler implements are detailed below under "Security".


## Scrambling Scrapers

To properly annoy scrapers, you'll need to somehow redirect their requests through the Scrambler. If you use Apache httpd, an easy way to do that is using [mod\_rewrite](https://httpd.apache.org/docs/current/mod/mod_rewrite.html). Here's an example:

```apacheconf
RewriteCond %{HTTP_USER_AGENT} GPTBot|Wget
RewriteCond %{REQUEST_URI} \.(html|php)$
RewriteCond %{REQUEST_URI} !^/cgi-bin/scrambler.py$
RewriteRule ^(.*) /cgi-bin/scrambler.py?honeypot=1&url=%{REQUEST_SCHEME}\%3A//%{HTTP_HOST}%{REQUEST_URI} [L]
```

The three lines starting with `RewriteCond` specify whose requests for what get scrambled:

1. Identify whose requests to scramble.
   - An easy way to do this is through [user agent](https://en.wikipedia.org/wiki/User-Agent_header) detection, though this relies on the scrapers being honest about what they are.
   - In this example, I'm scrambling requests from [GPTBot](https://platform.openai.com/docs/gptbot) (OpenAI's crawler) and [Wget](https://www.gnu.org/software/wget/) (an open-source download tool). I'm just picking on Wget to show how you can catch multiple programs with one line.
2. Identify what content to scramble.
   - How exactly you do this depends on what you used to build your website.
   - My example site is made up of static HTML files and PHP scripts, so I can filter requests by file extension. If you're running a complex web application, your `RewriteCond` may be more complicated.
3. Exempt the Scrambler itself from scrambling.
   - Otherwise, a bot that knows about the Scrambler can create an [infinite loop](https://en.wikipedia.org/wiki/Infinite_loop) by endlessly redirecting it to itself. Web servers (and hosting companies!) tend not to like those.

Beware this isn't [Stack Overflow](https://stackoverflow.blog/2021/09/28/become-a-better-coder-with-this-one-weird-click/). Understand what those lines mean and customize them for your own site.

The `RewriteRule` on the last line is what sends these naughty requests through the Scrambler. This one is usually safe to use as-is, assuming you put the Scrambler under `/cgi-bin`. Note the `honeypot=1` in the query string, which activates some additional restrictions (see "Security" below for details).

To avoid confusing more helpful bots, like the ones that index sites for search engines, you should probably block them from accessing the Scrambler directly. The following lines in your `robots.txt` should do it:

```robots
User-agent: *
Disallow: /cgi-bin/scrambler.py
```

Legitimate scrapers that obey `robots.txt` now know they're safe from scrambling. Naughty ones won't be hitting it through that URL -- to them it will look like they're accessing your website normally -- so it doesn't matter if they check `robots.txt` or not.

**The Scrambler is not intended to provide serious protection from scraping.** While I hope it is effective, the real point is to amuse humans rather than to frustrate bots, because all technical measures to prevent scraping can be circumvented. The proper way to address this misbehavior is through [regulation](https://www.schneier.com/blog/archives/2023/08/zoom-can-spy-on-your-calls-and-use-the-conversation-to-train-ai-but-says-that-it-wont.html). AI companies know this, which is why every time it comes up they change the subject to [bad science fiction](https://arstechnica.com/information-technology/2023/05/openai-execs-warn-of-risk-of-extinction-from-artificial-intelligence-in-new-open-letter/). Regulation, of course, is a complicated subject, and I'm not going to get into the details here.


## Security

The Scrambler implements a few basic precautions to prevent abuse:

* It is restricted to your own site by default, and can only access other sites if you explicitly allow them (see "Installation" above).
* It only allows accessing sites through HTTP and HTTPS on their respective [well-known ports](https://en.wikipedia.org/wiki/List_of_TCP_and_UDP_port_numbers#Well-known_ports). This is because non-standard ports are typically used for non-public internal purposes.
* It blocks JavaScript to prevent undesirable behaviors, both intended (like tracking) and unintended (like weird side effects from scrambling).

Adding `honeypot=1` to the query string (see "Scrambling Scrapers") further restricts access for your unwelcome visitors:

* Access to other sites is blocked completely, even if they're on your allowlist. This is so scrapers don't suck up all your bandwidth if you've linked to and allowlisted a huge site like Wikipedia.
* Access to linked content the Scrambler can't scramble, like PDF files, is also blocked. (This does not apply to embedded content like images.)

While I believe the Scrambler is reasonably safe, beware that it is probably not bulletproof. As always when using random code from the Internet, *caveat emptor*.
