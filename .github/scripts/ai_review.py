import os
import json
import subprocess
import sys
import requests

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
REPO         = os.environ["REPO"]
PR_NUM       = os.environ["PR_NUMBER"]


raw_diff = subprocess.check_output(
    ["git", "diff", "origin/main...HEAD", "--unified=3"],
    text=True,
)


def strip_test_files(diff_text: str) -> str:
    """Remove test file diffs before sending to the model.
    This is layer 1 of noise suppression. The model never sees
    test fixture credentials so it cannot flag them."""
    filtered = []
    skip = False
    for line in diff_text.splitlines():
        if line.startswith("diff --git"):
            skip = any(
                marker in line
                for marker in ["/tests/", "_test.py", "test_.py", "conftest.py"]
            )
        if not skip:
            filtered.append(line)
    return "\n".join(filtered)


diff = strip_test_files(raw_diff)
diff = diff[:10000]  # hard cap - keeps token cost low

if not diff.strip():
    print("No reviewable diff detected after filtering. Exiting.")
    sys.exit(0)


SYSTEM_PROMPT = """
You are a Principal Security Engineer and Senior Code Reviewer at a B2B fintech company.
Review the following Git diff and identify issues in ONLY these three categories:

1. SECURITY    - SQL injection, command injection, auth bypass, secrets or credentials
                 hardcoded in source files (excluding test directories)
2. LOGIC       - Race conditions, missing database transaction locks, incorrect financial
                 calculations, operations that corrupt data under concurrent load
3. RELIABILITY - External HTTP or I/O calls with no timeout and no exception handling;
                 failure modes that cause data loss or leave the system inconsistent

DO NOT comment on: variable naming, code formatting, style, test coverage,
documentation, or missing type hints.
DO NOT flag hardcoded strings or tokens in files under /tests/ or ending in _test.py.

For each finding return a JSON object with exactly these fields:
  "severity"         : one of CRITICAL, HIGH, MEDIUM, LOW
  "category"         : one of SECURITY, LOGIC, RELIABILITY
  "file"             : filename
  "line_range"       : approximate affected lines, e.g. "42-48"
  "title"            : one-line summary
  "description"      : plain-language explanation for developers and managers
  "exploit_scenario" : one sentence worst-case production outcome
  "suggested_fix"    : specific code-level recommendation

Respond with a raw JSON array only. No markdown fences. No prose.
If you find no issues return: []
""".strip()


print("Sending diff to GitHub Models for review...")

response = requests.post(
    "https://models.inference.ai.azure.com/chat/completions",
    headers={
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Content-Type": "application/json",
    },
    json={
        "model": "gpt-4o",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Review this diff:\n\n{diff}"},
        ],
        "max_tokens": 2000,
    },
)

if response.status_code != 200:
    print(f"GitHub Models call failed: {response.status_code} - {response.text}")
    sys.exit(1)

raw = response.json()["choices"][0]["message"]["content"].strip()

if raw.startswith("```"):
    raw = "\n".join(raw.split("\n")[1:])
    if raw.endswith("```"):
        raw = raw[:raw.rfind("```")]
    raw = raw.strip()

try:
    findings = json.loads(raw)
except json.JSONDecodeError as exc:
    print(f"Could not parse model response as JSON: {exc}")
    print(f"Raw response: {raw}")
    sys.exit(1)

if not isinstance(findings, list):
    print("Unexpected response structure. Expected a JSON array.")
    sys.exit(1)

if not findings:
    print("AI review complete. No issues found. Pipeline passed.")
    sys.exit(0)


lines = [
    "## AI Code Review - B2B Billing API",
    "",
    f"**{len(findings)} issue(s) found.** Review all findings before merging.",
    "",
    "---",
    "",
]

for i, f in enumerate(findings, 1):
    sev  = f.get("severity", "LOW")
    cat  = f.get("category", "")
    file = f.get("file", "")
    lr   = f.get("line_range", "N/A")
    lines.append(f"### Finding {i} - {sev} | {cat} | `{file}` lines {lr}")
    lines.append(f"**{f.get('title', '')}**")
    lines.append("")
    lines.append("**What is the problem?**")
    lines.append(f.get("description", ""))
    lines.append("")
    lines.append("**Worst-case production outcome:**")
    lines.append(f.get("exploit_scenario", ""))
    lines.append("")
    lines.append("**Recommended fix:**")
    lines.append(f.get("suggested_fix", ""))
    lines.append("")
    lines.append("---")
    lines.append("")

comment_body = "\n".join(lines)


post = requests.post(
    f"https://api.github.com/repos/{REPO}/issues/{PR_NUM}/comments",
    headers={
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    },
    json={"body": comment_body},
)

if post.status_code not in (200, 201):
    print(f"Failed to post PR comment: {post.status_code} - {post.text}")
    sys.exit(1)

print(f"Review comment posted to PR #{PR_NUM}.")


critical = [f for f in findings if f.get("severity") == "CRITICAL"]
if critical:
    print(f"PIPELINE BLOCKED: {len(critical)} CRITICAL finding(s) must be resolved before merge.")
    sys.exit(1)

print("No CRITICAL findings. Pipeline passed.")