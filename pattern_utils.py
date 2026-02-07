"""Tag pattern detection utilities for Docker image tags.

Analyzes tag lists from registries to automatically detect version patterns
and base tags (like 'latest', 'stable', etc.).
"""

import re
from typing import List, Dict, Any


# ---------------------------------------------------------------------------
# Known Patterns
# ---------------------------------------------------------------------------

KNOWN_PATTERNS = {
    r"^[0-9]+\.[0-9]+\.[0-9]+$": "Semantic version (X.Y.Z)",
    r"^v[0-9]+\.[0-9]+\.[0-9]+$": "Semantic version with v (vX.Y.Z)",
    r"^v[0-9]+\.[0-9]+\.[0-9]+-ls[0-9]+$": "LinuxServer with v (vX.Y.Z-lsN)",
    r"^[0-9]+\.[0-9]+\.[0-9]+-ls[0-9]+$": "LinuxServer (X.Y.Z-lsN)",
    r"^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+-ls[0-9]+$": "LinuxServer 4-part (W.X.Y.Z-lsN)",
    r"^[0-9]+\.[0-9]+\.[0-9]+-r[0-9]+-ls[0-9]+$": "LinuxServer with revision (X.Y.Z-rN-lsN)",
    r"^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+-[0-9a-f]+$": "Version with git hash (W.X.Y.Z-hash)",
    r"^[0-9]+\.[0-9]+$": "Major.Minor (X.Y)",
}

# Tags that are pure noise and should be filtered out
_NOISE_TAGS = {
    "latest", "nightly", "develop", "development", "dev", "edge", "master",
    "main", "stable", "unstable", "testing", "beta", "alpha", "rc", "next",
    "canary", "preview", "experimental", "plexpass", "public", "alpine",
}


# ---------------------------------------------------------------------------
# Internal Helper Functions
# ---------------------------------------------------------------------------

def _tokenize_tag(tag: str) -> List[tuple]:
    """Parse a tag into typed tokens: (type, literal).

    Token types: PREFIX_V, NUM, DOT, DASH, ALPHA, HEX
    """
    tokens = []
    i = 0
    length = len(tag)

    while i < length:
        ch = tag[i]

        if ch == '.':
            tokens.append(('DOT', '.'))
            i += 1
        elif ch == '-':
            # Look ahead: hex sequence (>=7 hex chars) after a dash
            rest = tag[i + 1:]
            hex_match = re.match(r'^([0-9a-f]{7,})(?=$|[^0-9a-zA-Z])', rest)
            if hex_match:
                tokens.append(('DASH', '-'))
                tokens.append(('HEX', hex_match.group(1)))
                i += 1 + len(hex_match.group(1))
            else:
                tokens.append(('DASH', '-'))
                i += 1
        elif ch.isdigit():
            j = i
            while j < length and tag[j].isdigit():
                j += 1
            tokens.append(('NUM', tag[i:j]))
            i = j
        elif ch.isalpha():
            j = i
            while j < length and tag[j].isalpha():
                j += 1
            word = tag[i:j]
            # 'v' before digits is a PREFIX_V
            if word == 'v' and j < length and tag[j].isdigit() and not tokens:
                tokens.append(('PREFIX_V', 'v'))
            else:
                tokens.append(('ALPHA', word))
            i = j
        else:
            # Skip unexpected characters
            i += 1

    return tokens


def _signature_from_tokens(tokens: List[tuple]) -> str:
    """Build a hashable signature string from token types.

    ALPHA tokens include their literal so that 'ls' and 'rc' produce
    different signatures.
    """
    parts = []
    for ttype, literal in tokens:
        if ttype == 'ALPHA':
            parts.append(f'ALPHA:{literal}')
        else:
            parts.append(ttype)
    return '|'.join(parts)


def _regex_from_token_groups(token_groups: List[List[tuple]]) -> str:
    """Generate an anchored regex from a list of token sequences sharing the
    same signature.

    For each position:
      NUM    -> [0-9]+
      DOT    -> \\.
      DASH   -> -
      PREFIX_V -> v
      HEX    -> [0-9a-f]+
      ALPHA  -> literal if all identical, else [a-z]+
    """
    if not token_groups:
        return ''

    # Use first group as the template (all share the same signature)
    template = token_groups[0]
    parts = []

    for pos, (ttype, _) in enumerate(template):
        if ttype == 'NUM':
            parts.append('[0-9]+')
        elif ttype == 'DOT':
            parts.append('\\.')
        elif ttype == 'DASH':
            parts.append('-')
        elif ttype == 'PREFIX_V':
            parts.append('v')
        elif ttype == 'HEX':
            parts.append('[0-9a-f]+')
        elif ttype == 'ALPHA':
            # Check if all groups have the same literal at this position
            literals = {group[pos][1] for group in token_groups}
            if len(literals) == 1:
                parts.append(literals.pop())
            else:
                parts.append('[a-z]+')

    return '^' + ''.join(parts) + '$'


def _auto_label(regex: str) -> str:
    """Generate a human-readable label from a regex pattern."""
    label = regex.strip('^$')

    # Build a readable representation
    replacements = [
        ('[0-9]+', 'N'),
        ('\\.', '.'),
        ('[0-9a-f]+', 'hash'),
        ('[a-z]+', 'text'),
    ]
    readable = label
    for old, new in replacements:
        readable = readable.replace(old, new)

    return f"Pattern: {readable}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_tag_patterns(tags: List[str]) -> List[Dict[str, Any]]:
    """Detect structural tag patterns from a list of registry tags.

    Returns a list of dicts sorted by match_count descending:
        {regex, label, match_count, example_tags}
    """
    if not tags:
        return []

    # 1. Filter noise
    filtered = []
    for tag in tags:
        low = tag.lower()
        # Skip pure-alpha noise tags
        if low in _NOISE_TAGS:
            continue
        # Skip single-char tags
        if len(tag) <= 1:
            continue
        # Skip sha refs
        if tag.startswith('sha-') or tag.startswith('sha256:'):
            continue
        # Skip arch suffixes as standalone tags
        if re.match(r'^(linux-)?(amd64|arm64|arm64v8|armhf|i386|s390x)$', low):
            continue
        # Skip tags ending with arch suffixes (e.g., "latest-amd64", "10.11.4-amd64")
        if re.search(r'-(amd64|arm64|arm64v8|armhf|i386|s390x)$', low):
            continue
        # Skip pure-alpha tags (all letters, no digits)
        if re.match(r'^[a-zA-Z][-a-zA-Z]*$', tag):
            continue
        filtered.append(tag)

    if not filtered:
        return []

    # Build index for recency: last in list = most recently pushed
    tag_index = {tag: i for i, tag in enumerate(filtered)}

    # 2. Tokenize each tag
    tokenized = []  # list of (tag, tokens)
    for tag in filtered:
        tokens = _tokenize_tag(tag)
        if tokens:
            tokenized.append((tag, tokens))

    # 3. Group by signature
    groups: Dict[str, List] = {}  # signature -> list of (tag, tokens)
    for tag, tokens in tokenized:
        sig = _signature_from_tokens(tokens)
        groups.setdefault(sig, []).append((tag, tokens))

    # 4. Generate regex per group, filter groups with <2 tags
    results = []
    for sig, members in groups.items():
        if len(members) < 2:
            continue

        token_groups = [tokens for _, tokens in members]
        regex = _regex_from_token_groups(token_groups)
        if not regex:
            continue

        # Compile and verify it actually matches the tags
        try:
            compiled = re.compile(regex)
        except re.error:
            continue

        matching_tags = [tag for tag, _ in members if compiled.match(tag)]
        if len(matching_tags) < 2:
            continue

        # 5. Match against KNOWN_PATTERNS for label
        label = KNOWN_PATTERNS.get(regex) or _auto_label(regex)

        # Pick example tags (up to 3, newest first — last in list = most recent)
        examples = matching_tags[-3:][::-1]

        # Track recency: index of the most recently pushed tag in this group
        most_recent_idx = max(tag_index[t] for t in matching_tags)

        results.append({
            'regex': regex,
            'label': label,
            'match_count': len(matching_tags),
            'example_tags': examples,
            '_recency': most_recent_idx,
        })

    # 6. Sort by recency (most recently pushed pattern first)
    results.sort(key=lambda r: r.pop('_recency'), reverse=True)

    return results


def detect_base_tags(tags: List[str], version_patterns: List[Dict[str, Any]]) -> List[str]:
    """Detect likely base tags (non-version tags like 'latest', 'stable', 'lts').

    Finds tags that don't match any detected version pattern, filtering out
    architecture variants and other noise. Returns tags sorted by recency
    (most recently pushed first).
    """
    if not tags:
        return []

    # Compile version regexes from detected patterns
    compiled = []
    for p in version_patterns:
        try:
            compiled.append(re.compile(p['regex']))
        except re.error:
            continue

    candidates = []
    for tag in tags:
        low = tag.lower()
        # Skip single-char tags
        if len(tag) <= 1:
            continue
        # Skip sha refs
        if tag.startswith('sha-') or tag.startswith('sha256:'):
            continue
        # Skip architecture tags
        if re.match(r'^(linux-)?(amd64|arm64|arm64v8|armhf|i386|s390x)$', low):
            continue
        if re.search(r'-(amd64|arm64|arm64v8|armhf|i386|s390x)$', low):
            continue
        # Skip tags that match any detected version pattern
        if any(r.match(tag) for r in compiled):
            continue
        candidates.append(tag)

    # Most recently pushed last in list → reverse for recency-first
    candidates.reverse()
    return candidates
