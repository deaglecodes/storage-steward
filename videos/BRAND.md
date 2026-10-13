# storage-steward video kit

The look, rules, assets and code for every storage-steward film. Each film prompt points here and only adds its story.
Sources: https://deaglecodes.github.io/storage-steward/ (site/index.html), assets/logo.svg, README.md, bench/results/.

## The brief (from the interview, 7 Oct 2026)
- Plays: launch video with sound (README, site, X). Format: 16:9, 1920x1080, 60 fps. Length: 40 s (20 bars at 120 BPM).
- Music: original score synthesized for the film (`tools/synth.py`), royalty-free. Any 120 BPM track can replace it without re-cutting.
- Must show: the df panel (a 1 TB drive filling vs. staying flat), `steward.py scan` / `sweep` in a terminal, proof (benchmark numbers).
- Ingredients: logo animation (draws itself) · big punchlines, word by word · a magic move (terminal becomes the df panel on the drop) · no cursor.
- Ending: logo lockup, "Works with" agent chips, the GitHub URL.

## Hard rules
- Casing: the product name is lowercase `storage-steward` everywhere (README, site).
- Type: display Bricolage Grotesque 800 for headlines and punchlines; Public Sans for body; JetBrains Mono for terminal, data and labels (site/index.html `--f-*`).
- Corners: 14 px cards and 999 px chips on the site, scaled to 22–26 px at 1080p film size.
- Surfaces: page `#0a1018`; card `#101926`; terminal panels `#060b12` with a 1.5 px `#1b2a40` ring (the site's dark theme). No other surfaces.
- Borders and shadows: rings only, no drop shadows except the hero panel's soft shadow (not used on a dark film background).
- Copy: plain words, sentence case, no em-dash asides (README voice).
- Claims: see "Claims".

## Color
| Token | Value | Use |
|---|---|---|
| background | `#0a1018` | every frame |
| foreground | `#edf2f8` | punchlines, numbers |
| muted foreground | `#98a5b7` | labels |
| surface | `#101926` | KPI tiles, agent chips |
| terminal | `#060b12` / ring `#1b2a40` | terminal and df panels |
| accent | `#6ea2ff` (text) / `#4d8dff` (logo, meters) | key words, storage-steward bars, URL |
| status: full | `#f07a49` | DISK FULL, the manual-wipe series |
| status: kept / AUTO | `#2fbf86` | AUTO chip, "swept" |
| no-cleanup series | `#6b7686` | the growing meter |

## Signature elements
| Element | Look | Source | In films |
|---|---|---|---|
| df panel | dark terminal card, label + GB + 1 TB meter, dashed divider, day scrub | site hero `.panel`, `.df-row` | twin (`Df.tsx`), frame-driven |
| Tier chips | AUTO / CONFIRM / INFO pills in mono | site `.chip`, `steward.py scan` | in the terminal scan |
| KPI tiles | big Bricolage number + muted label | site `.kpi` | proof scene |
| Agent chips | pill on surface with ring | site `.chipset` | ending |

## Logo
- `assets/logo.svg`: a dark tile, a disk ring, a reclaimed blue segment pulled out, a blue spindle.
- Animation: the ring draws (stroke-dashoffset), the blue segment pops out along its bisector on a spring, the spindle lands. `Logo.tsx`, driven by `t`.

## Components
| Need | Component | In films |
|---|---|---|
| Terminal | site `.cmd` / `.panel` | redraw (`Panel.tsx`): static CSS, typing is frame-driven |
| df rows | site hero `df()` | twin (`Df.tsx`): the site animates with CSS transitions |
| Punchlines | kit `punchlines.tsx` | as is |

## Motion
- Springs: kit defaults (glide 150/20 for the magic move, 170/22 for tiles rising, 210/16 for the logo pop).
- Words land in 0.3 s on cubic-bezier(0.22, 1, 0.36, 1) (kit).
- No SVG `<text>` under an animated CSS `scale`/`transform`. In batched renders, Chrome keeps SVG text laid out at a stale scale, so every render tab draws it somewhere else and the motion blur stacks the copies. Single-frame stills look fine, so check a batched segment (`remotion render --frames=…`) of any zooming scene. Use HTML text instead.

## Claims
- May show: the 60-day simulation (79–85% less disk, 0 deliverables lost, 1 vs 878 cache re-downloads), token evals (58–86% fewer task tokens, 72% averaged), hooks cost 0 tokens per prompt, works with Claude Code, Codex, Cursor and Gemini CLI.
- Terminal sizes are demo data from the same 60-day model (heavy user, day 14, no cleanup), in the tool's real output format.
- Never: claim real-user savings, guarantee a size, or show the tool deleting user files.

## Launch v2 (`src/videos/launch2/`, 45 s, 24 bars at 128 BPM)
Feedback on v1: it looked like you still had to prompt for a cleanup, and it needed bigger transitions and a way to show people choosing what goes and what stays. v2 tells it in six acts, each a pure function of `t` on the bar grid in `cues.ts`:

| Bars | Act | Beat | Transition out |
|---|---|---|---|
| 1–2 | `OpenAct` | four agent windows spill leftovers into a pile; the disk gauge climbs to 96% | everything is sucked into the gauge (zoom ×16) |
| 3–4 | `PunchAct` | "Your agents leave files behind." inside the full disk | the frame slices into strips |
| 5 | `ChoreAct` | MON–THU hard cuts of manual `rm -rf`, the last one deleting a real file | tape stop to black |
| 6–12 | `HubAct` | logo draws, `./install.sh` hooks four agents, a week of time-lapse: every session end sweeps by itself, nobody types a command | whip pan |
| 13–16 | `RulesAct` | plain-English asks become `steward.py config …` and land as rows in the policy | zoom through the AUTO chip (×36) |
| 17–24 | `ProofAct`, `EndAct` | the 60-day chart and a DISK FULL stamp, four proof slams, the 2×2, then the lockup | green flash in, collapse to the logo |

- Score: `tools/score_v2.py` (E minor, sections cut to the acts, SFX written alongside). `Launch2.tsx` mixes everything at `MIX = 0.6`. The final mix is about −13 LUFS with a true peak of −2 dBTP.
- Claims used: 85% less disk, 0 files lost, 72% fewer tokens (60-day simulation and token evals), 0 tokens per prompt, 61 ms hook (`bench/results/hook_latency.json`, median 60.8 ms). The time-lapse GB values are illustrative and labeled TIME-LAPSE.
- Render: `bun scripts/render.ts Launch2 storage-steward-launch-v2 --duration 45 --poster 44.3`.

## Launch v3, the minimal cut (`src/videos/launch3/`, 32 s, 16 bars at 120 BPM)
The film for the minimal site. It uses the site's light theme and its type: Bricolage Grotesque for display, the system UI and mono faces for the rest. No agent is named; the copy says "your agent" and "any agent that reads SKILL.md". Every scene leaves the same way: the blue sweep line crosses it and leaves a clean page, landing on the next bar.

| Bars | Scene | What happens |
|---|---|---|
| 1–4 | `Mess` | leftovers flood the page and the meter fills; "Your agents leave files behind."; a two-bar sweep erases everything |
| 5–6 | `Less` | "Less." letter by letter, the dot lands on beat 3; "storage-steward cleans up while your agents work." |
| 7–8 | `Clone` | "Clone it into your agent." and the install command typed; "Works with any agent that reads SKILL.md." |
| 9–10 | `Forget` | sessions run along a track; a background sweep clears what they leave, every few sessions; "Sweeps in the background. 0 tokens per prompt." |
| 11–12 | `Rules` | a plain-English ask becomes one `steward.py config` line |
| 13–14 | `Proof` | 79–85% less disk, 72% fewer tokens, 0 files lost, with their source |
| 15–16 | `End` | the logo draws, the wordmark, "Works with any agent that reads SKILL.md.", the URL |

- Score: `tools/score_v3.py`, one file with no separate SFX. Typing ticks, sweeps and stat hits sit on the same cue numbers as `cues.ts`.
- Render: `bun scripts/render.ts Launch3 storage-steward-launch-v3 --duration 32 --poster 31.2`.

## Workspace
- `videos/` (Remotion 4.0.530 pinned, React 19.3.0; all packages ≥ 7 days old via `npm install --before`).
- Fonts via `@remotion/google-fonts`. Music via `tools/synth.py`; beat grid checked with `scripts/beats.py`.
- Scripts from the product-film skill: `stills.ts`, `render.ts`, `verify.py`, `beats.py`, `audio-edit.py`.
