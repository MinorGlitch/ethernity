# CLAUDE.md

## Design Context

### Users
Security-conscious operators and individuals who need offline-capable secret recovery. They interact with the browser recovery kit during potentially stressful moments (key recovery, disaster scenarios), often with limited connectivity. They value verifiability and independence from cloud services.

### Brand Personality
**Bold, Minimalist, Authoritative.** The kit communicates confidence and precision without visual noise. Professional and direct — no decoration for its own sake. Every element serves a functional purpose. The interface should feel like a well-engineered security tool: unambiguous, clean, and trustworthy.

### Aesthetic Direction
Visual tone is precise and utilitarian with restrained elegance. Reference: 1Password / Bitwarden design sensibility — clear hierarchy, strong contrast, purposeful use of space.

- **Light mode** (current): Slate-blue palette with `--bg: #eef2f7`, `--accent: #1f5fce`, clean white panels
- **Dark mode**: Support both themes; users should be able to toggle
- **Typography**: system-ui stack, 13px base, monospace for data/code inputs
- **Spacing**: Compact grid-based layouts, `8px` border-radius panels, tight but breathable
- **Colors**: Keep current palette. Status colors: green (`--ok: #177a53`), amber (`--warn: #a36412`), red (`--err: #bb3f3f`). Avoid bright reds/oranges outside of error states

### Design Principles

1. **Clarity over decoration.** Every visual element must communicate function. No gradients, shadows, or flourishes unless they improve comprehension.
2. **Offline-first confidence.** The interface must feel complete and safe without network access. The offline guard is a security feature, not a limitation — treat it as a trust signal.
3. **Information hierarchy drives decisions.** Use size, weight, color, and spacing to direct attention to the most important actions. Recovery is a linear workflow — make the next step obvious.
4. **Accessible under stress.** Users may be recovering from data loss. Text must be readable, contrast must be strong, and actions must be unambiguous. Reduced motion, keyboard navigation, and screen reader support matter.
