# Installation appearance

`COMMONS_THEME=charcoal` (default) or `blue-slate` selects the existing preset.
`COMMONS_APPEARANCE` optionally supplies a JSON object of dark appearance tokens.
Overlays own this configuration; the shared product contains no installation-specific
palette or identity checks. Compose forwards it to the application. Changing it
requires an authorized application restart/recreation, but no source edit or rebuild.

Example (synthetic):

```sh
export COMMONS_APPEARANCE='{"accent":"#80CCFF","font":"mono"}'
```

| Token | Meaning | Partial-config fallback |
| --- | --- | --- |
| background | Outer page and navigation | `#08090a` |
| surface | Main content | `#0d0e10` |
| raised | Dialogs, inputs and cards | `#131416` |
| hover | Hovered controls and rows | `#17181b` |
| selected | Selected controls and rows | `#1c1d20` |
| border | Neutral separators and control borders | `#25262a` |
| foreground | Primary text | `#eeeeef` |
| secondary | Secondary text | `#c5c6cc` |
| muted | Tertiary text | `#9a9ca5` |
| accent | Keyboard focus and primary buttons | `#aeb4c6` |
| font | `system` or `mono`, local font stacks only | `system` |

Precedence: a valid nonempty appearance object uses the complete palette above,
with supplied tokens replacing those defaults, over either preset. A missing,
blank or empty object leaves the selected preset unchanged. Malformed JSON,
unknown keys, non-string values, non-six-digit hex colors, unsupported fonts or
unsafe contrast reject the whole customization and log a value-free warning;
the configured preset remains usable. This atomic fallback avoids combining an
invalid text token with an otherwise accepted background. No per-user appearance
preference currently exists; navigation/reading preferences are unrelated.

Only dark palettes are supported: each background/surface must have relative
luminance at most 0.035, every text token must contrast at least 4.5:1 against all
five surfaces, and the accent must contrast at least 3:1 against them. Primary
button text is automatically black or white, whichever has higher contrast.
Semantic error/warning and record-kind colors remain unchanged. Subtle separators
are decorative; focus uses a separate high-contrast accent outline. These checks
cover configured roles, not a claim of a complete accessibility audit.

The document loads `/api/appearance.css` as a render-blocking stylesheet before
application rendering. This public endpoint contains only validated appearance
values, requires no database/session query, and uses `Cache-Control: no-store`.
It accepts no CSS, URLs, arbitrary font names or private configuration paths.
If unavailable, the existing preset styles remain the fallback. Valid custom
palettes are present before the first application paint; existing blue-slate
preset selection still comes from the health response as before.

Neutral retained styles use custom properties with their exact original literal
fallbacks, preserving the default presentation. Do not replace semantic colors
with generic appearance colors. Test the resolver with `cargo test --locked`
(or `rustc --edition 2024 --test src/appearance.rs -o /tmp/commons-appearance-tests`
for a dependency-free diagnostic), then use the repository check/verify lanes
and inspect representative rendered states before deployment.
