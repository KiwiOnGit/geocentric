# Game Development & Game Loop Engineering Skill

## Purpose
Use this skill when tasked with building terminal-based mini-games, dynamic Web/HTML5 canvas games, interactive adventure branches, or game-loop architectures.

## 1. Core Directives
1. **Never build basic text logs**: Ensure the game has a defined game-loop loop, robust game states, interactive choice prompts, and high visual engagement (CSS variables/animations for web, ascii grids/framing for terminal).
2. **Modular State Tracking**: Abstract game state variables (e.g. score, player coordinates, inventory, health) into a clean state object. Never use global variables.
3. **Interactive Terminals**:
   - For python game loops requiring keyboard input, always use standard syntax-checking.
   - Use `<agent_terminal command="python game.py" timeout="30">` with appropriate `<input>` packets to verify and test playability.

## 2. Structural Architecture
A modular game loop should operate as follows:
```
           [ 1. Init ] -> Setup state, canvas/terminal grids, assets
             │
      ┌───►[ 2. Input ] -> Capture keys, terminal stdin, clicks
      │      │
      │    [ 3. Update ] -> Move entities, collision checks, stats
      │      │
      │    [ 4. Render ] -> Paint UI, print ASCII grids, draw canvas
      └──────┘
```

## 3. High-Quality Code Examples

### HTML5 Canvas Premium Game Loop with Acceleration
```javascript
class CanvasGame {
  constructor(canvasId) {
    this.canvas = document.getElementById(canvasId);
    this.ctx = this.canvas.getContext('2d');
    this.state = {
      player: { x: 50, y: 150, vx: 0, vy: 0, speed: 4, radius: 10 },
      isGameOver: false
    };
    this.keys = {};
    window.addEventListener('keydown', e => this.keys[e.key] = true);
    window.addEventListener('keyup', e => this.keys[e.key] = false);
  }

  update() {
    const p = this.state.player;
    if (this.keys['ArrowRight']) p.vx = p.speed;
    else if (this.keys['ArrowLeft']) p.vx = -p.speed;
    else p.vx *= 0.85; // friction

    p.x += p.vx;
    // Boundary collision check
    p.x = Math.max(p.radius, Math.min(this.canvas.width - p.radius, p.x));
  }

  render() {
    this.ctx.fillStyle = '#0b0f19';
    this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);

    // Render player with glow
    this.ctx.shadowBlur = 10;
    this.ctx.shadowColor = '#6366f1';
    this.ctx.fillStyle = '#6366f1';
    this.ctx.beginPath();
    this.ctx.arc(this.state.player.x, this.state.player.y, this.state.player.radius, 0, Math.PI * 2);
    this.ctx.fill();
  }

  start() {
    const loop = () => {
      if (this.state.isGameOver) return;
      this.update();
      this.render();
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  }
}
```
