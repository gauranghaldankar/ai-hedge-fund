#!/usr/bin/env bash
# Mobile pipeline: build a native or cross-platform app to the current store standard.
# Build is the easy part; the STORE-READINESS gate (privacy/signing/review) is the hard,
# externally-enforced wall. Interactive on Max is the primary path; this is the headless
# reference. Verify flags with `claude --help`.
set -euo pipefail
PROJ="${1:?usage: pipeline-mobile.sh <project-dir>}"
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

stage(){ echo; echo "########## $1 ##########"; }
ask(){ claude -p "$1" --permission-mode acceptEdits; }

stage "2-3 Requirements (product-manager)"
ask "As product-manager: requirements + tickets for the mobile app. Include the target platforms and the store-review lead time in release planning (review queues + Google closed-testing add weeks)."

stage "6 Architecture (architect)"
ask "As architect: decide native vs cross-platform (Swift/SwiftUI · Kotlin/Compose · Flutter/RN/KMP) and RECORD IT AS AN ADR. Define data, secure-storage, and integration design."

stage "7 Design (ux-designer + mobile-hig skill)"
ask "As ux-designer using the mobile-hig skill: platform-correct flows, all screen states, tokens, dark mode, accessibility, AND adaptive large-screen layouts — window size classes, list-detail/split-view for tablet/iPad, foldable postures, both orientations, external input. No phone-only design."

stage "8 Build (mobile-engineer)"
ask "As mobile-engineer: implement the slice in the chosen stack. Consent-gate all tracking SDKs (no init before consent). Secure storage only. Tests alongside."

stage "GATE (stack-aware, per-project, bounded)"
echo "  bash $ROOT/scripts/gate.sh --project $PROJ    # detects Package.swift / gradle; bounded loop"

stage "9-10 Review + Device-matrix QA"
ask "As code-reviewer then qa-engineer using the device-matrix skill: review the diff; run the OS x form-factor matrix INCLUDING a tablet and a foldable config, both orientations, and multi-window. Check for letterboxing/stretched layouts. Crash-free smoke is mandatory — a launch crash is the #1 rejection."

stage "11 Mobile security + privacy (security-engineer)"
ask "As security-engineer using mobile-threat-model AND mobile-privacy-compliance skills: OWASP MASVS scan; verify privacy labels / Data Safety match ACTUAL SDK behavior; ATT + Privacy Manifests; account deletion; age-verification where required. Critical/High block. Route legal-sensitive items to legal."

stage "12 Performance (performance-engineer + mobile-perf)"
ask "As performance-engineer using mobile-perf: baseline startup, jank, memory, app size, battery/wake-locks (now a store-ranking factor), ANR. Flag regressions."

stage "13-14 Docs + STORE-READINESS gate (docs-writer, mobile-release-engineer)"
ask "As docs-writer then mobile-release-engineer: write docs; assemble the store-readiness go/no-go (current SDK version, signing, accurate privacy labels, required behaviors, large-screen/universal support with tablet+foldable assets and iPad screenshots, crash-free, listing+screenshots match). Web-search current store deadlines. STOP before submission."

echo; echo "Founder approval boundary: submitting to the App Store / Play is YOURS. The deck assembles the go/no-go; you press submit."
