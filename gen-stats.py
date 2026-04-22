#!/usr/bin/env python3
"""Generate languages.svg — aggregates bytes across all repos (incl private)."""
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

def fetch():
    # /user/repos is viewer-scoped: returns all repos the token can see
    # (public + private), including those owned by the authenticated user.
    # More reliable than `gh repo list <username>` which can silently drop
    # private repos depending on token scope interpretation.
    r = subprocess.run(
        ['gh', 'api', '--paginate',
         '/user/repos?visibility=all&affiliation=owner&per_page=100'],
        capture_output=True, text=True, check=True)
    # --paginate concatenates JSON arrays — parse each array chunk
    raw = r.stdout.strip()
    repos = []
    # gh --paginate joins arrays as "][": split and re-parse chunks
    for chunk in raw.replace('][', ']\n[').split('\n'):
        repos.extend(json.loads(chunk))
    repos = [x for x in repos if not x.get('fork') and not x.get('archived')]
    totals = collections.Counter()
    for x in repos:
        full = x['full_name']
        o = subprocess.run(['gh', 'api', f'/repos/{full}/languages'],
                           capture_output=True, text=True, check=True)
        for k, v in json.loads(o.stdout).items():
            totals[k] += v
    return totals, len(repos)

def esc(s): return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

def render(totals, repo_count):
    grand = sum(totals.values())
    items = [(k, v) for k, v in totals.most_common() if v * 100 / grand >= 0.4]

    W, pad = 495, 22
    row_h = 28
    bar_w = 280
    bar_x = W - pad - bar_w
    header_h = 62
    footer_h = 38
    H = header_h + row_h * len(items) + footer_h

    svg = [
        f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" role="img">',
        f'<rect width="{W}" height="{H}" rx="10" fill="{BG}" stroke="{BORDER}" stroke-width="1"/>',
        f'<text x="{pad}" y="30" fill="{TITLE}" font-family="-apple-system,Segoe UI,sans-serif" font-size="16" font-weight="700" letter-spacing=".02em">Languages</text>',
        f'<text x="{pad}" y="50" fill="{VALUE}" font-family="-apple-system,Segoe UI,sans-serif" font-size="11">across {repo_count} repositories · public + private</text>',
    ]

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

def main():
    totals, n = fetch()
    svg = render(totals, n)
    out = sys.argv[1] if len(sys.argv) > 1 else 'languages.svg'
    with open(out, 'w') as f:
        f.write(svg)
    print(f"Wrote {out} — {len(totals)} languages across {n} repos")

if __name__ == '__main__':
    main()
