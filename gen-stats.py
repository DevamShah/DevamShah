#!/usr/bin/env python3
"""Generate languages.svg + stats.svg from all repos (public + private).

Needs a gh CLI auth context (GH_TOKEN or `gh auth login`) whose token has
read access to private repos — classic PAT with 'repo' scope, or fine-grained
with Contents:Read + Metadata:Read on all owned repos.
"""
import subprocess, json, collections, datetime, sys

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
    return [x for x in repos if not x.get('fork') and not x.get('archived')]


def fetch_languages(repos):
    totals = collections.Counter()
    for x in repos:
        langs = json.loads(gh(['gh', 'api', f'/repos/{x["full_name"]}/languages']))
        for k, v in langs.items():
            totals[k] += v
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


def render_languages(totals, repo_count):
    grand = sum(totals.values())
    items = [(k, v) for k, v in totals.most_common() if v * 100 / grand >= 0.4]

    W, pad = 495, 22
    row_h = 28
    bar_w = 280
    bar_x = W - pad - bar_w
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
        svg.append(f'<text x="{pad}" y="{y+14}" fill="{LABEL}" font-family="-apple-system,Segoe UI,sans-serif" font-size="13" font-weight="500">{esc(name)}</text>')
        svg.append(f'<text x="{bar_x-10}" y="{y+14}" text-anchor="end" fill="{VALUE}" font-family="ui-monospace,SFMono-Regular,Menlo,monospace" font-size="12">{pct:.1f}%</text>')
        svg.append(f'<rect x="{bar_x}" y="{y+4}" width="{bar_w}" height="10" rx="5" fill="{TRACK}"/>')
        svg.append(f'<rect x="{bar_x}" y="{y+4}" width="{bar_fill}" height="10" rx="5" fill="{fill}"/>')
        y += row_h

    total_mb = grand / (1024 * 1024)
    today = datetime.date.today().isoformat()
    svg.append(f'<text x="{pad}" y="{H-14}" fill="{VALUE}" font-family="ui-monospace,SFMono-Regular,Menlo,monospace" font-size="10" letter-spacing=".04em">{total_mb:.1f} MB indexed · updated {today}</text>')
    svg.append('</svg>')
    return '\n'.join(svg)


def render_stats(repos, lang_count, total_bytes, profile):
    total_repos = len(repos)
    public_repos = sum(1 for r in repos if not r.get('private'))
    private_repos = total_repos - public_repos
    total_stars = sum(r.get('stargazers_count', 0) for r in repos)

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
    repos = fetch_repos()
    langs = fetch_languages(repos)
    profile = fetch_profile_stats()

    with open('languages.svg', 'w') as f:
        f.write(render_languages(langs, len(repos)))
    with open('stats.svg', 'w') as f:
        f.write(render_stats(repos, len(langs), sum(langs.values()), profile))

    print(f"languages.svg — {len(langs)} languages across {len(repos)} repos")
    print(f"stats.svg     — {len(repos)} repos · {sum(r.get('stargazers_count',0) for r in repos)} stars")


if __name__ == '__main__':
    main()
