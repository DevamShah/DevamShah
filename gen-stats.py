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

# Non-code formats — counted by cloc but excluded from the "languages I write"
# display. Data, docs, config — not programming output.
NON_CODE_LANGUAGES = {
    "Markdown", "JSON", "JSON5", "JSON with Comments", "YAML", "TOML",
    "INI", "CSV", "Text", "XML", "SVG", "Properties", "diff",
    "make", "CMake", "Bazel",
}


def fetch_loc(repos):
    """Shallow-clone each repo, run cloc, aggregate LOC by language."""
    totals = collections.Counter()
    token = os.environ.get('GH_TOKEN', '').strip()
    if not token:
        print("  WARNING: GH_TOKEN empty — private clones will fail", file=sys.stderr)
    workdir = tempfile.mkdtemp(prefix='loc-')
    ok = 0
    skipped = 0
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
            except subprocess.CalledProcessError as e:
                stderr = (e.stderr or '').replace(token, '***')
                print(f"  skip {full}: clone failed exit={e.returncode} {stderr[:200]}", file=sys.stderr)
                skipped += 1
                continue
            except subprocess.TimeoutExpired:
                print(f"  skip {full}: clone timed out", file=sys.stderr)
                skipped += 1
                continue

            repo_loc = 0
            try:
                out = subprocess.run(
                    ['cloc', '--json', '--quiet', dest],
                    capture_output=True, text=True, timeout=180, check=False,
                )
                if not out.stdout.strip():
                    print(f"  skip {full}: cloc empty (stderr={out.stderr[:120]})", file=sys.stderr)
                    skipped += 1
                    continue
                data = json.loads(out.stdout)
            except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
                print(f"  skip {full}: cloc failed ({e})", file=sys.stderr)
                skipped += 1
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
                repo_loc += code
            ok += 1
            print(f"  ok   {full}: {repo_loc:,} LOC", file=sys.stderr)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    print(f"  → {ok} ok, {skipped} skipped, total {sum(totals.values()):,} LOC", file=sys.stderr)
    return totals


def fetch_contributions():
    """Public PRs to external repos (not owned by USERNAME), grouped by state.

    Paginates so the count never silently caps at 100 — important as the
    external-contribution volume scales into the hundreds.
    """
    query = """query($u:String!, $after:String) {
      user(login:$u) {
        pullRequests(first: 100, after: $after, orderBy: {field: CREATED_AT, direction: DESC}) {
          pageInfo { hasNextPage endCursor }
          nodes {
            title url state mergedAt createdAt
            additions deletions changedFiles
            repository { nameWithOwner owner { login } isPrivate stargazerCount url description }
          }
        }
      }
    }"""
    nodes, after = [], None
    while True:
        args = ['gh', 'api', 'graphql', '-f', f'query={query}', '-F', f'u={USERNAME}']
        if after:
            args += ['-F', f'after={after}']
        page = json.loads(gh(args))['data']['user']['pullRequests']
        nodes += page['nodes']
        if not page['pageInfo']['hasNextPage']:
            break
        after = page['pageInfo']['endCursor']
    return [
        n for n in nodes
        if n['repository']['owner']['login'] != USERNAME
        and not n['repository']['isPrivate']
    ]


def fmt_stars(n):
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def render_contributions_md(prs):
    """Build markdown block for the README contributions section.

    Two parts:
      1. Projects showcase — deduped per-repo with merged/open/closed counts.
      2. Pull-request detail table — every PR with diff + state.
    """
    if not prs:
        return "_No external open-source contributions tracked yet._"

    state_emoji = {"MERGED": "✅ Merged", "OPEN": "🟡 In review", "CLOSED": "⚪ Closed"}
    state_order = {"MERGED": 0, "OPEN": 1, "CLOSED": 2}

    # ---- Aggregate per-repo ----
    repos = {}
    for p in prs:
        r = p['repository']['nameWithOwner']
        if r not in repos:
            repos[r] = {
                'name': r,
                'url': p['repository']['url'],
                'stars': p['repository']['stargazerCount'],
                'description': p['repository'].get('description') or '',
                'merged': 0, 'open': 0, 'closed': 0,
                'lines_added': 0, 'lines_removed': 0,
            }
        bucket = p['state'].lower()
        if bucket in repos[r]:
            repos[r][bucket] += 1
        if p['state'] == 'MERGED':
            repos[r]['lines_added'] += p['additions']
            repos[r]['lines_removed'] += p['deletions']

    merged = sum(1 for p in prs if p['state'] == 'MERGED')
    opn = sum(1 for p in prs if p['state'] == 'OPEN')
    closed = sum(1 for p in prs if p['state'] == 'CLOSED')

    summary = f"**{merged} merged · {opn} in review · {closed} closed** across **{len(repos)}** external project(s)."

    # ---- Projects showcase ----
    proj_lines = ["", "### Projects with accepted contributions", ""]
    # sort: most merged first, then by stars
    proj_sorted = sorted(repos.values(), key=lambda r: (-r['merged'], -r['stars']))
    for r in proj_sorted:
        badges = []
        if r['merged']:
            badges.append(f"✅ {r['merged']} merged")
        if r['open']:
            badges.append(f"🟡 {r['open']} in review")
        if r['closed']:
            badges.append(f"⚪ {r['closed']} closed")
        badge_str = " · ".join(badges)
        desc = r['description'].strip()
        desc_part = f" — _{desc}_" if desc else ""
        impact = ""
        if r['merged']:
            impact = f" · merged diff **+{r['lines_added']:,} / −{r['lines_removed']:,}**"
        proj_lines.append(
            f"- **[{r['name']}]({r['url']})** ({fmt_stars(r['stars'])} ⭐){desc_part}<br>"
            f"&nbsp;&nbsp;{badge_str}{impact}"
        )

    # ---- PR detail table ----
    table_lines = [
        "",
        "<details>",
        "<summary><b>All pull requests</b></summary>",
        "",
        "| Repository | ⭐ | Pull Request | Diff | Status |",
        "|---|---:|---|---:|---|",
    ]
    sorted_prs = sorted(
        prs,
        key=lambda p: (
            state_order.get(p['state'], 99),
            -(p['repository']['stargazerCount']),
            -(p['additions'] + p['deletions']),
        ),
    )
    for p in sorted_prs:
        repo = p['repository']
        stars = fmt_stars(repo['stargazerCount'])
        title = p['title'].replace('|', '\\|')
        if len(title) > 70:
            title = title[:67] + "…"
        pr_num = p['url'].rsplit('/', 1)[-1]
        diff = f"+{p['additions']:,} / −{p['deletions']:,}"
        status = state_emoji.get(p['state'], p['state'])
        table_lines.append(
            f"| [{repo['nameWithOwner']}]({repo['url']}) | {stars} | [#{pr_num}]({p['url']}) {title} | {diff} | {status} |"
        )
    table_lines.append("")
    table_lines.append("</details>")

    return '\n'.join([summary] + proj_lines + table_lines)


def render_hero_badge(prs):
    """A live, top-of-profile badge pair making merged OSS PRs the hero stat."""
    merged = sum(1 for p in prs if p['state'] == 'MERGED')
    repos = {p['repository']['nameWithOwner'] for p in prs if p['state'] == 'MERGED'}
    return (
        f'<img src="https://img.shields.io/badge/OSS_Merged_PRs-{merged}-d4a24c'
        f'?style=for-the-badge&logo=github&logoColor=d4a24c&labelColor=0a0f22">\n'
        f'<img src="https://img.shields.io/badge/Across-{len(repos)}_security_projects-0a0f22'
        f'?style=for-the-badge&labelColor=0a0f22">'
    )


def update_marker(readme_path, start, end, content, label=""):
    """Replace content between an HTML-comment marker pair. Returns True if changed."""
    with open(readme_path) as f:
        text = f.read()
    if start not in text or end not in text:
        print(f"  README: {label or start} markers missing, skipping", file=sys.stderr)
        return False
    pre = text.split(start)[0]
    post = text.split(end)[1]
    new = f"{pre}{start}\n{content}\n{end}{post}"
    if new == text:
        return False
    with open(readme_path, 'w') as f:
        f.write(new)
    return True


def update_readme(readme_path, contributions_md):
    """Replace content between <!-- contributions:start --> and <!-- contributions:end -->."""
    return update_marker(readme_path, "<!-- contributions:start -->",
                         "<!-- contributions:end -->", contributions_md, "contributions")


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
    """Both bar % and ordering use LOC — keeps the visual math consistent.

    Iterate over loc_totals (cloc) rather than totals (Linguist bytes) so that
    high-LOC languages cloc detects but Linguist doesn't (e.g. YAML, JSON,
    Markdown, Dockerfile) are not silently dropped.
    """
    code_loc = {k: v for k, v in loc_totals.items() if k not in NON_CODE_LANGUAGES}
    grand_loc = sum(code_loc.values()) or 1
    grand_bytes = sum(totals.values()) or 1
    items = [
        (k, v) for k, v in code_loc.items()
        if v * 100 / grand_loc >= 0.4
    ]
    items.sort(key=lambda kv: -kv[1])

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
    for name, loc in items:
        pct = loc * 100 / grand_loc
        fill = COLORS.get(name, FALLBACK)
        bar_fill = max(2, int(bar_w * pct / 100))
        svg.append(f'<text x="{pad}" y="{y+14}" fill="{LABEL}" font-family="-apple-system,Segoe UI,sans-serif" font-size="13" font-weight="500">{esc(name)}</text>')
        svg.append(f'<text x="{bar_x-10}" y="{y+14}" text-anchor="end" fill="{VALUE}" font-family="ui-monospace,SFMono-Regular,Menlo,monospace" font-size="12">{pct:.1f}%</text>')
        svg.append(f'<rect x="{bar_x}" y="{y+4}" width="{bar_w}" height="10" rx="5" fill="{TRACK}"/>')
        svg.append(f'<rect x="{bar_x}" y="{y+4}" width="{bar_fill}" height="10" rx="5" fill="{fill}"/>')
        svg.append(f'<text x="{loc_x}" y="{y+14}" text-anchor="end" fill="{ACCENT}" font-family="ui-monospace,SFMono-Regular,Menlo,monospace" font-size="12" font-weight="600">{fmt_loc(loc)} LOC</text>')
        y += row_h

    total_mb = grand_bytes / (1024 * 1024)
    today = datetime.date.today().isoformat()
    svg.append(f'<text x="{pad}" y="{H-14}" fill="{VALUE}" font-family="ui-monospace,SFMono-Regular,Menlo,monospace" font-size="10" letter-spacing=".04em">% by lines of code · {total_mb:.1f} MB · {fmt_loc(grand_loc)} LOC · updated {today}</text>')
    svg.append('</svg>')
    return '\n'.join(svg)


def render_stats(repos, lang_count, total_bytes, loc_totals, profile):
    total_repos = len(repos)
    public_repos = sum(1 for r in repos if not r.get('private'))
    private_repos = total_repos - public_repos
    total_stars = sum(r.get('stargazers_count', 0) for r in repos)
    code_loc = sum(v for k, v in loc_totals.items() if k not in NON_CODE_LANGUAGES)
    total_loc = code_loc

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

    print("fetching public contributions…", file=sys.stderr)
    prs = fetch_contributions()
    print(f"  {len(prs)} external PRs (merged/open/closed)", file=sys.stderr)

    with open('languages.svg', 'w') as f:
        f.write(render_languages(langs, loc_totals, len(repos)))
    with open('stats.svg', 'w') as f:
        f.write(render_stats(repos, len(langs), sum(langs.values()), loc_totals, profile))

    contributions_md = render_contributions_md(prs)
    if update_readme('README.md', contributions_md):
        print("README.md — contributions section updated")
    else:
        print("README.md — no change (or markers missing)")

    if update_marker('README.md', "<!-- merged-badge:start -->",
                     "<!-- merged-badge:end -->", render_hero_badge(prs), "hero-badge"):
        print("README.md — hero badge updated")

    print(f"languages.svg — {len(langs)} languages across {len(repos)} repos · {sum(loc_totals.values()):,} LOC")
    print(f"stats.svg     — {len(repos)} repos · {sum(r.get('stargazers_count',0) for r in repos)} stars")


if __name__ == '__main__':
    main()
