# Frontend UI/UX Engineering Skill

## Purpose
Use this skill when building web applications, single-page sites, games, or styling dashboard screens.

## 1. Core Directives
1. **Never use boring default styling**: Always enforce rich premium aesthetics, including tailored harmonious CSS variables, glassmorphism, rounded corners, soft shadows, sleek hover interactions, and subtle micro-animations.
2. **Modern Typography & Hierarchy**: Use curated font imports (e.g., "Outfit", "Inter", "Poppins" from Google Fonts) instead of plain generic browser defaults. Set explicit line-heights (1.4 - 1.5).
3. **Viewport Alignment**: Implement visual viewports correctly. Align all button and input elements inside their respective CSS container grids or flex structures so they never overflow.
4. **Visual Self-Verification Loop**: 
   - Start local servers using `<run_bg_command>`.
   - Take a screenshot with `<capture_view url="http://localhost:5000" file="screenshot.png" />`.
   - Iterate at least 3 times to correct elements that are out of place or don't look beautiful.

## 2. Structural Architecture
A premium frontend structure should always be organized as follows:
```
├── css/
│   ├── variables.css      # HSL-based harmonious theme tokens
│   ├── base.css           # Global resets and modern scrollbars
│   ├── components.css     # Buttons, inputs, widgets, modals
│   └── layouts.css        # Responsive flex/grid shells
├── js/
│   ├── state.js           # Lightweight reactive state store
│   ├── api.js             # SSE stream readers & HTTP calls
│   ├── ui.js              # DOM dynamic builders
│   └── main.js            # Entry point & listeners
└── index.html             # Clean semantic layout structure
```

## 3. High-Quality Code Examples

### CSS Variable System & Dark Theme
```css
:root {
  --font-main: 'Outfit', sans-serif;
  --bg-main: #0b0f19;
  --bg-panel: #111827;
  --bg-panel-hover: #1f2937;
  --text-main: #f3f4f6;
  --text-muted: #9ca3af;
  --accent: #6366f1;
  --accent-soft: rgba(99, 102, 241, 0.15);
  --border: rgba(255, 255, 255, 0.08);
  --radius-lg: 12px;
  --shadow-lg: 0 10px 30px -10px rgba(0, 0, 0, 0.5);
  --transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}

body {
  font-family: var(--font-main);
  background-color: var(--bg-main);
  color: var(--text-main);
  margin: 0;
  line-height: 1.5;
}

/* Glassmorphism Panel Example */
.premium-card {
  background: rgba(17, 24, 39, 0.7);
  backdrop-filter: blur(12px);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  transition: var(--transition);
}
.premium-card:hover {
  transform: translateY(-2px);
  border-color: rgba(99, 102, 241, 0.3);
}
```

### Micro-Animations
```css
@keyframes float {
  0% { transform: translateY(0px); }
  50% { transform: translateY(-4px); }
  100% { transform: translateY(0px); }
}
.floating-element {
  animation: float 4s ease-in-out infinite;
}
```
