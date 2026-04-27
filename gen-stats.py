#!/usr/bin/env python3
"""Generate languages.svg + stats.svg from all repos (public + private).

Needs a gh CLI auth context (GH_TOKEN or `gh auth login`) whose token has
read access to private repos — classic PAT with 'repo' scope, or fine-grained
with Contents:Read + Metadata:Read on all owned repos.
"""
import subprocess, json, collections, datetime, sys, os, tempfile, shutil

USERNAME = "DevamShah"

# Curated palette — visually distinct, matches portfolio dark/gold aesthetic.
COLORS = {
    "Python":     "#d4a24c",
    "TypeScript": "#60a5fa",
    "HTML":       "#e06b4e",
    "JavaScript": "#34d399",
    "Shell":      "#a78bfa",
    "CSS":        "#94a3b8",
    "Go":         "#8dd0e0",
    "Rust":       "#f4a261",
    "Ruby":       "#e63946",
    "Java":       "#ffb86b",
    "C":          "#c7a6e8",
    "C++":        "#d28b8b",
}
FALLBACK = "#7a84a0"

BG      = "#0a0f22"
BORDER  = "#1a2340"
TITLE   = "#d4a24c"
LABEL   = "#e8e4df"
VALUE   = "#9da3b8"
TRACK   = "#151e40"
ACCENT  = "#eab84e"


def gh(args, check=True):
    r = subprocess.run(args, capture_output=True, text=True, check=check)
    return r.stdout


def fetch_repos():
    raw = gh(['gh', 'api', '--paginate',
              '/user/repos?visibility=all&affiliation=owner&per_page=100']).strip()
    repos = []
    for chunk in raw.replace('][', ']\n[').split('\n'):
        repos.extend(json.loads(chunk))
    return [x for x in repos if not x.get('archived')]


def fetch_languages(repos):
    totals = collections.Counter()
    for x in repos:
        langs = json.loads(gh(['gh', 'api', f'/repos/{x["full_name"]}/languages']))
        for k, v in langs.items():
            totals[k] += v
    return totals


# cloc → GitHub Linguist language-name normalization for languages where
# the two tools disagree. Anything not in this map is passed through as-is.
CLOC_TO_LINGUIST = {
    "Bourne Shell":      "Shell",
    "Bourne Again Shell":"Shell",
    "Dockerfile":        "Dockerfile",
    "Markdown":          "Markdown",
    "YAML":              "YAML",
    "JSON":              "JSON",
    "Jupyter Notebook":  "Jupyter Notebook",
    "C/C++ Header":      "C++",
}


def fetch_loc(repos):
    """Shallow-clone each repo, run cloc, aggregate LOC by language."""
    totals = collections.Counter()
    token = os.environ.get('GH_TOKEN', '')
    workdir = tempfile.mkdtemp(prefix='loc-')
    try:
        for r in repos:
            full = r['full_name']
            url = f'https://x-access-token:{token}@github.com/{full}.git'
            dest = os.path.join(workdir, r['name'])
            try:
                subprocess.run(
                    ['git', 'clone', '--depth=1', '--quiet', url, dest],
                    check=True, capture_output=True, text=True, timeout=120,
                )
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                print(f"  skip {full}: clone failed ({e})", file=sys.stderr)
                continue

            try:
                out = subprocess.run(
                    ['cloc', '--json', '--quiet', '--vcs=git', dest],
                    capture_output=True, text=True, timeout=180, check=False,
                )
                if not out.stdout.strip():
                    continue
                data = json.loads(out.stdout)
            except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
                print(f"  skip {full}: cloc failed ({e})", file=sys.stderr)
                continue
            finally:
                shutil.rmtree(dest, ignore_errors=True)

            for lang, info in data.items():
                if lang in ('header', 'SUM'):
                    continue
                code = info.get('code', 0)
                if code <= 0:
                    continue
                key = CLOC_TO_LINGUIST.get(lang, lang)
                totals[key] += code
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return totals


def fetch_profile_stats():
    """Uses GraphQL for accurate public+private contribution counts."""
    query = """query($u:String!) {
      user(login:$u) {
        createdAt
        contributionsCollection {
          totalCommitContributions
          totalPullRequestContributions
          totalIssueContributions
          totalPullRequestReviewContributions
          restrictedContributionsCount
        }
      }
    }"""
    out = gh(['gh', 'api', 'graphql', '-f', f'query={query}', '-F', f'u={USERNAME}'])
    return json.loads(out)['data']['user']


def esc(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def svg_open(w, h):
    return [
        f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" role="img">',
        f'<rect width="{w}" height="{h}" rx="10" fill="{BG}" stroke="{BORDER}" stroke-width="1"/>',
    ]


def fmt_loc(n):
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def render_languages(totals, loc_totals, repo_count):
    grand = sum(totals.values())
    items = [(k, v) for k, v in totals.most_common() if v * 100 / grand >= 0.4]

    W, pad = 560, 22
    row_h = 28
    bar_w = 240
    bar_x = W - pad - bar_w - 70   # leave 70px on the right for "LOC"
    loc_x = W - pad
    header_h = 62
    footer_h = 38
    H = header_h + row_h * len(items) + footer_h

    svg = svg_open(W, H)
    svg.append(f'<text x="{pad}" y="30" fill="{TITLE}" font-family="-apple-system,Segoe UI,sans-serif" font-size="16" font-weight="700" letter-spacing=".02em">Languages</text>')
    svg.append(f'<text x="{pad}" y="50" fill="{VALUE}" font-family="-apple-system,Segoe UI,sans-serif" font-size="11">across {repo_count} repositories · public + private</text>')

    y = header_h
    for name, bytes_ in items:
        pct = bytes_ * 100 / grand
        fill = COLORS.get(name, FALLBACK)
        bar_fill = max(2, int(bar_w * pct / 100))
        loc = loc_totals.get(name, 0)
        svg.append(f'<text x="{pad}" y="{y+14}" fill="{LABEL}" font-family="-apple-system,Segoe UI,sans-serif" font-size="13" font-weight="500">{esc(name)}</text>')
        svg.append(f'<text x="{bar_x-10}" y="{y+14}" text-anchor="end" fill="{VALUE}" font-family="ui-monospace,SFMono-Regular,Menlo,monospace" font-size="12">{pct:.1f}%</text>')
        svg.append(f'<rect x="{bar_x}" y="{y+4}" width="{bar_w}" height="10" rx="5" fill="{TRACK}"/>')
        svg.append(f'<rect x="{bar_x}" y="{y+4}" width="{bar_fill}" height="10" rx="5" fill="{fill}"/>')
        svg.append(f'<text x="{loc_x}" y="{y+14}" text-anchor="end" fill="{ACCENT}" font-family="ui-monospace,SFMono-Regular,Menlo,monospace" font-size="12" font-weight="600">{fmt_loc(loc)} LOC</text>')
        y += row_h

    total_mb = grand / (1024 * 1024)
    total_loc = sum(loc_totals.values())
    today = datetime.date.today().isoformat()
    svg.append(f'<text x="{pad}" y="{H-14}" fill="{VALUE}" font-family="ui-monospace,SFMono-Regular,Menlo,monospace" font-size="10" letter-spacing=".04em">{total_mb:.1f} MB · {fmt_loc(total_loc)} lines of code · updated {today}</text>')
    svg.append('</svg>')
    return '\n'.join(svg)


def render_stats(repos, lang_count, total_bytes, loc_totals, profile):
    total_repos = len(repos)
    public_repos = sum(1 for r in repos if not r.get('private'))
    private_repos = total_repos - public_repos
    total_stars = sum(r.get('stargazers_count', 0) for r in repos)
    total_loc = sum(loc_totals.values())

    contrib = profile['contributionsCollection']
    commits_12mo = contrib['totalCommitContributions'] + contrib['restrictedContributionsCount']
    prs = contrib['totalPullRequestContributions']
    reviews = contrib['totalPullRequestReviewContributions']
    issues = contrib['totalIssueContributions']

    created = datetime.datetime.fromisoformat(profile['createdAt'].replace('Z', '+00:00'))
    member_yrs = (datetime.datetime.now(created.tzinfo) - created).days / 365.25

    rows = [
        ("Repositories",        f"{total_repos}",    f"{public_repos} public · {private_repos} private"),
        ("Languages shipped",   f"{lang_count}",     f"{total_bytes / (1024*1024):.1f} MB indexed"),
        ("Lines of code",       f"{fmt_loc(total_loc)}", "across all source files"),
        ("Stars received",      f"{total_stars}",    "across public repositories"),
        ("Commits (12 mo)",     f"{commits_12mo:,}", "public + private contributions"),
        ("Pull requests",       f"{prs}",            f"authored · {reviews} reviewed"),
        ("Issues authored",     f"{issues}",         ""),
    ]

    W, pad = 495, 22
    row_h = 28
    header_h = 62
    footer_h = 38
    H = header_h + row_h * len(rows) + footer_h

    svg = svg_open(W, H)
    svg.append(f'<text x="{pad}" y="30" fill="{TITLE}" font-family="-apple-system,Segoe UI,sans-serif" font-size="16" font-weight="700" letter-spacing=".02em">Profile</text>')
    svg.append(f'<text x="{pad}" y="50" fill="{VALUE}" font-family="-apple-system,Segoe UI,sans-serif" font-size="11">aggregate stats · public + private</text>')

    label_x = pad
    value_x = pad + 190
    note_x = pad + 260
    y = header_h
    for label, value, note in rows:
        svg.append(f'<text x="{label_x}" y="{y+14}" fill="{LABEL}" font-family="-apple-system,Segoe UI,sans-serif" font-size="13" font-weight="500">{esc(label)}</text>')
        svg.append(f'<text x="{value_x}" y="{y+14}" fill="{ACCENT}" font-family="ui-monospace,SFMono-Regular,Menlo,monospace" font-size="14" font-weight="700">{esc(value)}</text>')
        if note:
            svg.append(f'<text x="{note_x}" y="{y+14}" fill="{VALUE}" font-family="-apple-system,Segoe UI,sans-serif" font-size="11">{esc(note)}</text>')
        y += row_h

    today = datetime.date.today().isoformat()
    footer = f"Member since {created.strftime('%Y')} · {member_yrs:.1f} years on GitHub · updated {today}"
    svg.append(f'<text x="{pad}" y="{H-14}" fill="{VALUE}" font-family="ui-monospace,SFMono-Regular,Menlo,monospace" font-size="10" letter-spacing=".04em">{esc(footer)}</text>')
    svg.append('</svg>')
    return '\n'.join(svg)


def main():
    print("fetching repos…", file=sys.stderr)
    repos = fetch_repos()
    print(f"  {len(repos)} repos (forks included, archived excluded)", file=sys.stderr)

    print("fetching language bytes…", file=sys.stderr)
    langs = fetch_languages(repos)

    print("counting LOC via shallow clone + cloc…", file=sys.stderr)
    loc_totals = fetch_loc(repos)

    print("fetching profile stats…", file=sys.stderr)
    profile = fetch_profile_stats()

    with open('languages.svg', 'w') as f:
        f.write(render_languages(langs, loc_totals, len(repos)))
    with open('stats.svg', 'w') as f:
        f.write(render_stats(repos, len(langs), sum(langs.values()), loc_totals, profile))

    print(f"languages.svg — {len(langs)} languages across {len(repos)} repos · {sum(loc_totals.values()):,} LOC")
    print(f"stats.svg     — {len(repos)} repos · {sum(r.get('stargazers_count',0) for r in repos)} stars")


if __name__ == '__main__':
    main()
