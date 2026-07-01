# Storytelling & Narrative Worldbuilding Skill

## Purpose
Use this skill when drafting storyboards, game quests, character scripts, fantasy lore, or interactive text adventures.

## 1. Core Directives
1. **Compelling Pacing**: Build an engaging narrative arc (Exposition, Rising Action, Climax, Falling Action, Resolution).
2. **Character & Environment Depth**: Detail rich character descriptions, distinct dialogue voices, and atmospheric world designs.
3. **Interactive Branching**: For game scripts, ensure clear state tracking, choice menus, and clean logical outcomes.

## 2. Interactive Storytelling Architecture
When building text-based games or interactive choices, use a logical state tree:
```
               [ 1. Introduction ]
             /                    \
  Choice A: Venture West      Choice B: Explore East
           /                         \
  [ 2A. The Forgotten ruins ]    [ 2B. The Whispering Forest ]
         |                                |
  Finds Iron Key                   Finds Spell Scroll
```

## 3. High-Quality Narrative Examples

### Atmospheric Worldbuilding
```text
The city of Oakhaven lay buried beneath a shroud of sulfurous fog, its iron spires clawing at a grey sky that had forgotten the sun. Down in the cobbles, green gas lanterns flickered like dying fireflies, reflecting off puddles of greasy rain. The inhabitants walked with their shoulders hunched and eyes cast down, listening to the rhythmic, metallic heartbeat of the steam pumps churning deep below the streets. It was a place where copper was king and secrets were the only currency that truly mattered.
```

### Interactive Text Adventure Script Structure (Python)
```python
def start_game():
    print("THE CELLAR GATE")
    print("=================")
    print("You find yourself standing at the foot of a winding moss-covered stair.")
    print("To the left, a heavy wooden door is barred with rusty chains.")
    print("To the right, a damp tunnel slopes down into pitch darkness.")
    
    choice = input("\nDo you choose to explore the DOOR or the TUNNEL? ").strip().lower()
    
    if choice == "door":
        enter_door()
    elif choice == "tunnel":
        enter_tunnel()
    else:
        print("Invalid choice. Try again.")
        start_game()

def enter_door():
    print("\nYou approach the wooden door. The rusty chains rattle as you inspect them...")
    # Add puzzle logic here
```
