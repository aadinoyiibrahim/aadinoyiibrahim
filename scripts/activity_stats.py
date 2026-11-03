"""
Build a GitHub "Activity overview" figure for the profile README.

Panel (a): overall share of commits / pull requests / issues / code reviews
           over the last year (same quantity as GitHub's native cross chart).
Panel (b): the same four contribution types broken down per repository
           (top-N projects by total contributions).

Data source: GitHub GraphQL API, `user.contributionsCollection`
(default window = the last 365 days, identical to the profile heatmap).

Usage
-----
    GH_TOKEN=<token> python scripts/activity_stats.py --login aadinoyiibrahim --outdir figs/

What to expect (sanity check)
-----------------------------
* The four percentages in panel (a) sum to 100 and should be within a few
  points of the native chart on your profile. Small gaps are expected:
  the native chart hides repositories the viewer cannot read, and private
  contributions are only visible here if the token can see them.
* Per-repo bars in panel (b) need NOT add up to the totals in panel (a):
  GitHub only reports repositories the token may see, and contributions in
  private repos without access are dropped from the per-repo lists.
* A large mismatch (e.g. commits ~40 % here vs ~80 % on your profile) means
  the time window or token scope is wrong, not that your activity changed.
"""

import argparse
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker  # noqa: E402,F401
import requests  # noqa: E402

GRAPHQL_URL = "https://api.github.com/graphql"

# Order + colours shared by both panels.
KINDS = ["commits", "pull_requests", "issues", "reviews"]
LABELS = {
    "commits": "Commits",
    "pull_requests": "Pull requests",
    "issues": "Issues",
    "reviews": "Code review",
}
COLORS = {
    "commits": "#2da44e",
    "pull_requests": "#8250df",
    "issues": "#d4a72c",
    "reviews": "#0969da",
}
TEXT = "#8b949e"  # mid-grey: readable on GitHub light AND dark themes

QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      startedAt
      endedAt
      totalCommitContributions
      totalPullRequestContributions
      totalIssueContributions
      totalPullRequestReviewContributions
      restrictedContributionsCount
      totalRepositoryContributions
      contributionCalendar { totalContributions }
      commitContributionsByRepository(maxRepositories: 100) {
        repository { nameWithOwner isPrivate }
        contributions { totalCount }
      }
      pullRequestContributionsByRepository(maxRepositories: 100) {
        repository { nameWithOwner isPrivate }
        contributions { totalCount }
      }
      issueContributionsByRepository(maxRepositories: 100) {
        repository { nameWithOwner isPrivate }
        contributions { totalCount }
      }
      pullRequestReviewContributionsByRepository(maxRepositories: 100) {
        repository { nameWithOwner isPrivate }
        contributions { totalCount }
      }
    }
  }
}
"""


def fetch_contributions(login, token):
    """Return the raw `contributionsCollection` dict for `login`."""
    r = requests.post(
        GRAPHQL_URL,
        json={"query": QUERY, "variables": {"login": login}},
        headers={"Authorization": f"bearer {token}"},
        timeout=30,
    )
    r.raise_for_status()
    payload = r.json()
    if "errors" in payload:
        sys.exit(f"GraphQL error: {payload['errors']}")
    return payload["data"]["user"]["contributionsCollection"]


def summarise(cc):
    """Raw collection -> (totals, per_repo, period, meta).

    totals   : {kind: int}
    per_repo : {repo_name: {kind: int}}; private repos are pooled into one
               "private repositories (n)" row so their names never reach
               the public README.
    period   : (startedAt, endedAt) ISO strings
    meta     : {calendar, restricted, repos_created} -- the extra terms
               needed to reconcile with the heatmap total:
               calendar = sum(totals) + restricted + repos_created
    """
    totals = {
        "commits": cc["totalCommitContributions"],
        "pull_requests": cc["totalPullRequestContributions"],
        "issues": cc["totalIssueContributions"],
        "reviews": cc["totalPullRequestReviewContributions"],
    }
    field = {
        "commits": "commitContributionsByRepository",
        "pull_requests": "pullRequestContributionsByRepository",
        "issues": "issueContributionsByRepository",
        "reviews": "pullRequestReviewContributionsByRepository",
    }
    per_repo, private = {}, set()
    for kind, key in field.items():
        for item in cc[key]:
            repo = item["repository"]
            name = repo["nameWithOwner"]
            if repo["isPrivate"]:
                private.add(name)
                name = "PRIVATE"
            per_repo.setdefault(name, dict.fromkeys(KINDS, 0))
            per_repo[name][kind] += item["contributions"]["totalCount"]
    if "PRIVATE" in per_repo:
        per_repo[f"private repositories ({len(private)})"] = per_repo.pop("PRIVATE")
    meta = {
        "calendar": cc["contributionCalendar"]["totalContributions"],
        "restricted": cc["restrictedContributionsCount"],
        "repos_created": cc["totalRepositoryContributions"],
    }
    return totals, per_repo, (cc["startedAt"], cc["endedAt"]), meta


def _plot_cross(ax, totals, meta):
    """GitHub-style cross: arm length ∝ share of each contribution type."""
    n = sum(totals.values()) or 1
    pct = {k: 100 * v / n for k, v in totals.items()}
    # Same layout as GitHub: left=commits, down=PRs, right=issues, up=reviews.
    direction = {
        "commits": (-1, 0),
        "pull_requests": (0, -1),
        "issues": (1, 0),
        "reviews": (0, 1),
    }
    ax.axhline(0, color=TEXT, lw=0.6, alpha=0.4)
    ax.axvline(0, color=TEXT, lw=0.6, alpha=0.4)
    for k, (dx, dy) in direction.items():
        L = pct[k] / 100
        ax.plot([0, dx * L], [0, dy * L], color=COLORS[k], lw=5,
                solid_capstyle="round")
        if L > 0:  # no dot for an empty arm (would pile up at the centre)
            ax.plot(dx * L, dy * L, "o", color=COLORS[k], ms=8)
        # Label just beyond the axis end so it never overlaps the arm.
        tx, ty = dx * 1.18, dy * 1.18
        ha = {-1: "right", 0: "center", 1: "left"}[dx]
        va = {-1: "top", 0: "center", 1: "bottom"}[dy]
        ax.text(tx, ty, f"{pct[k]:.0f}%\n{LABELS[k]}", ha=ha, va=va,
                color=TEXT, fontsize=10, linespacing=1.3)
    ax.set_xlim(-1.9, 1.9)
    ax.set_ylim(-1.6, 1.6)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(f"(a) Activity overview  ·  {n} of {meta['calendar']} "
                 "contributions", color=TEXT, fontsize=11, loc="left")
    # Account for the rest of the heatmap total under the cross.
    rest = [f"{n} commits/PRs/issues/reviews"]
    if meta["restricted"]:
        rest.append(f"{meta['restricted']} private (type not visible)")
    if meta["repos_created"]:
        rest.append(f"{meta['repos_created']} repositories created")
    ax.text(0.5, -0.02, " + ".join(rest) + f" = {meta['calendar']}",
            transform=ax.transAxes, ha="center", va="top", color=TEXT,
            fontsize=8)


def _plot_per_repo(ax, per_repo, top_n):
    """Horizontal stacked bars: contributions per project, by type."""
    ranked = sorted(per_repo.items(), key=lambda kv: sum(kv[1].values()),
                    reverse=True)[:top_n]
    ranked = ranked[::-1]  # largest on top
    names = [name for name, _ in ranked]
    left = [0] * len(ranked)
    for k in KINDS:
        vals = [counts[k] for _, counts in ranked]
        ax.barh(names, vals, left=left, color=COLORS[k], label=LABELS[k],
                height=0.65)
        left = [a + b for a, b in zip(left, vals)]
    for y, total in enumerate(left):
        ax.text(total, y, f"  {total}", va="center", color=TEXT, fontsize=9)
    ax.set_xlabel("contributions (last 12 months)", color=TEXT)
    ax.tick_params(colors=TEXT, labelsize=9)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(TEXT)
    ax.set_xlim(0, max(left or [1]) * 1.15)
    ax.xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))
    ax.set_title(f"(b) Top {len(ranked)} projects", color=TEXT, fontsize=11,
                 loc="left")
    leg = ax.legend(frameon=False, fontsize=9, loc="lower right")
    for t in leg.get_texts():
        t.set_color(TEXT)


def plot_activity(totals, per_repo, period, meta, outdir_, top_n=8):
    """Two-panel figure saved as <outdir_>/activity_overview.png."""
    fig, (ax_a, ax_b) = plt.subplots(
        1, 2, figsize=(13, 4.6), gridspec_kw={"width_ratios": [1, 1.6]}
    )
    _plot_cross(ax_a, totals, meta)
    _plot_per_repo(ax_b, per_repo, top_n)
    fig.text(0.99, 0.01, f"{period[0][:10]} → {period[1][:10]}",
             ha="right", color=TEXT, fontsize=8)
    fig.tight_layout()
    os.makedirs(outdir_, exist_ok=True)
    plt.savefig(outdir_ + "activity_overview.png", dpi=300,
                bbox_inches="tight", transparent=True)
    plt.close(fig)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    p.add_argument("--login", default="aadinoyiibrahim")
    p.add_argument("--outdir", default="figs/")
    p.add_argument("--top", type=int, default=8)
    args = p.parse_args()

    token = os.environ.get("GH_TOKEN")
    if not token:
        sys.exit("Set GH_TOKEN (any GitHub token; a personal one also counts "
                 "private contributions).")
    outdir_ = args.outdir if args.outdir.endswith("/") else args.outdir + "/"

    totals, per_repo, period, meta = summarise(
        fetch_contributions(args.login, token))
    plot_activity(totals, per_repo, period, meta, outdir_, top_n=args.top)

    n = sum(totals.values()) or 1
    print("period:", period)
    for k in KINDS:
        print(f"  {LABELS[k]:<14} {totals[k]:>5}  ({100 * totals[k] / n:.1f}%)")
    print(f"  repositories: {len(per_repo)}")
    # Sanity check: the pieces must add up to the heatmap number.
    parts = n_raw = sum(totals.values())
    parts += meta["restricted"] + meta["repos_created"]
    print(f"  {n_raw} + {meta['restricted']} private + {meta['repos_created']}"
          f" repos created = {parts}  (heatmap: {meta['calendar']})")
    if parts != meta["calendar"]:
        print("  WARNING: does not reconcile with the heatmap total")


if __name__ == "__main__":
    main()
