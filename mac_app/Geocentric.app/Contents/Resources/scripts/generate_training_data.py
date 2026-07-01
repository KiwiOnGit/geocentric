import json
from pathlib import Path
import random

def main():
    print("Generating massive, high-quality synthetic training datasets...")
    
    # ----------------- 1. Create Pretraining Corpus -----------------
    pretrain_concepts = [
        # AI & Transformers
        "A transformer language model predicts the next token in a sequence autoregressively by utilizing self-attention layers.",
        "Self-attention dynamically calculates a set of attention weights representing the relationships between all tokens in a sequence.",
        "Multi-head self-attention splits the original input embeddings into multiple representation spaces to process them in parallel.",
        "Decoder-only causal models like GPT or Qwen use a causal lower-triangular mask to prevent tokens from looking at future tokens.",
        "The causal mask sets attention scores for future positions to negative infinity, which evaluates to exactly zero after softmax.",
        "Feed-forward layers (or MLP blocks) are applied after self-attention layers to project representation features into high-dimensional space.",
        "The MLP block typically consists of two linear layers with a GeLU (Gaussian Error Linear Unit) non-linear activation function.",
        "Gradient checkpointing trades computing time for VRAM by dropping intermediate activations and recomputing them during the backward pass.",
        "In PyTorch, block-level gradient checkpointing can be enabled using torch.utils.checkpoint.checkpoint on each transformer block.",
        "Layer normalization is applied before block sub-layers in pre-LN architectures, ensuring stable gradient flow in deep models.",
        "Autoregressive language models predict the probability distribution of the next word given all previously generated words.",
        "AdamW is an advanced optimization algorithm that decouples weight decay from the gradient update calculations of standard Adam.",
        "Masked cross-entropy loss in SFT sets target labels for user prompt tokens to -100, ignoring them during backpropagation.",
        "Byte-level BPE tokenizers build a vocabulary by iteratively merging the most frequent adjacent character or byte pairs.",
        
        # Python Programming
        "Python is a high-level, interpreted programming language widely used in AI, scripting, and modern web application development.",
        "Python is dynamically typed, meaning data types of variables are resolved at runtime rather than during compile-time.",
        "Python uses clean, indentation-based syntax instead of curly braces or semicolons to define structural code blocks.",
        "Functions in Python are defined using the 'def' keyword, supporting type hints, default values, and variable arguments.",
        "Lists in Python are ordered, mutable collections of objects supporting indexing, slicing, and clean list comprehensions.",
        "Dictionaries in Python are highly efficient key-value stores backed by hash tables, providing O(1) average lookup time.",
        "Object-oriented programming in Python supports inheritance, encapsulation, polymorphism, and constructors using __init__.",
        "Exception handling in Python isolates runtime errors gracefully using try, except, else, and finally block structures.",
        "Python modules allow developers to split large codebases into reusable, self-contained files and packages.",
        
        # Science & Physics
        "Gravity attracts any two objects with mass, and is described as spacetime curvature in Albert Einstein's general theory of relativity.",
        "Spacetime is a four-dimensional fabric combining space and time, which curves in the presence of mass and energy.",
        "The solar system consists of the Sun and the gravitationally bound planets, dwarf planets, moons, and asteroids orbiting it.",
        "Quantum mechanics describes matter and energy at atomic scales, introducing wave-particle duality and uncertainty principles.",
        "The Heisenberg uncertainty principle states that it is impossible to simultaneously measure a particle's position and momentum perfectly.",
        "Energy is a conserved physical quantity that can neither be created nor destroyed, only transformed from one form to another.",
        
        # General & Logic
        "Step-by-step reasoning (chain-of-thought) improves logical accuracy by letting models compute reasoning steps before answering.",
        "I am Geocentric, a generative AI assistant running 100% locally on your machine, ensuring absolute data privacy and security.",
        "Geocentric is a tiny, local transformer model trained entirely from scratch, utilizing PyTorch on Apple Silicon (MPS)."
    ]
    
    # Let's generate exactly 2,200 rich documents to give the model a massive, dense text diet!
    expanded_docs = []
    random.seed(42)
    for idx in range(2200):
        # Sample 3 random concepts and combine them into a rich document paragraph
        sampled = random.sample(pretrain_concepts, 3)
        doc_text = f"Document {idx}: " + " ".join(sampled) + " Guided fine tuning teaches the model to answer instructions after pretraining."
        expanded_docs.append(doc_text)
        
    pretrain_path = Path("data/pretrain_seed.txt")
    pretrain_path.parent.mkdir(parents=True, exist_ok=True)
    pretrain_path.write_text("\n".join(expanded_docs), encoding="utf-8")
    print(f"  Created pretrain corpus at {pretrain_path} ({len(expanded_docs)} documents, {len(pretrain_path.read_text(encoding='utf-8'))} bytes)")
    
    # ----------------- 2. Create Conversational SFT Dataset -----------------
    sft_templates = [
        # Persona & Hello
        {
            "instruction": "Who are you?",
            "response_template": "I am Geocentric, a locally-trained decoder-only artificial intelligence assistant. I operate entirely on your local machine, meaning all our conversations are private and no data ever leaves your device."
        },
        {
            "instruction": "Hello! How can you help me today?",
            "response_template": "Hello! I am Geocentric, your local AI assistant. I can help you with a wide range of tasks, including writing clean Python code, debugging complex neural networks, explaining scientific concepts, and solving logical problems step-by-step."
        },
        # Programming (Python, JavaScript)
        {
            "instruction": "Write a Python function to check if a word is a palindrome.",
            "response_template": "Here is a clean and robust Python function to check if a word is a palindrome, ignoring case and spaces:\n\n```python\ndef is_palindrome(word: str) -> bool:\n    \"\"\"\n    Checks if a string is a palindrome.\n    Ignores letter casing and non-alphanumeric characters.\n    \"\"\"\n    cleaned = \"\".join(char.lower() for char in word if char.isalnum())\n    return cleaned == cleaned[::-1]\n\n# Example:\nprint(is_palindrome(\"radar\"))  # True\nprint(is_palindrome(\"hello\"))  # False\n```"
        },
        {
            "instruction": "Explain how list comprehensions work in Python.",
            "response_template": "**List comprehensions** in Python provide a concise way to create lists. They are typically faster and more readable than standard `for` loops.\n\n### Syntax:\n```python\n[expression for item in iterable if condition]\n```\n\n### Example:\n```python\n# Double even numbers\ndoubled_evens = [x * 2 for x in range(10) if x % 2 == 0]\n# Result: [0, 4, 8, 12, 16]\n```"
        },
        # Deep Learning & AI
        {
            "instruction": "Explain the role of self-attention in a transformer model.",
            "response_template": "In a transformer model, **self-attention** allows the network to process text by relating each word (or token) in a sequence to all other words in the same sequence. \n\n### Core Concept:\nUnlike sequential models (RNNs) which process tokens one-by-step, self-attention processes the entire sequence in parallel. By computing Query (Q), Key (K), and Value (V) dot products, it creates context-aware embeddings representing word relationships."
        },
        {
            "instruction": "What is the function of the lower triangular mask in causal self-attention?",
            "response_template": "In causal self-attention, the **lower triangular mask** enforces the autoregressive constraint: a token cannot attend to any tokens that appear after it in the sequence.\n\n### Mechanism:\nDuring self-attention dot product calculation, scores for future positions are replaced with negative infinity ($-\\infty$). After softmax, these evaluate to zero, blocking information flow from future positions during training and inference."
        },
        # Math Equations
        {
            "instruction": "Solve for x in the equation: 3x + 12 = 27.",
            "response_template": "To solve the equation **3x + 12 = 27**:\n\n1. **Subtract 12** from both sides to isolate the variable term:\n   $$3x = 27 - 12$$\n   $$3x = 15$$\n\n2. **Divide both sides by 3**:\n   $$x = \\frac{15}{3}$$\n   $$x = 5$$\n\nTherefore, the solution is **x = 5**."
        }
    ]
    
    # We will expand this dynamically to exactly 160 rich conversational examples with customized variations
    expanded_sft = []
    
    # Conversational & logical logic expansion
    for i in range(25):
        for t in sft_templates:
            # Let's clone and customize
            cloned = {}
            if "3x + 12 = 27" in t["instruction"]:
                # Customize math values to keep the model learning diverse coefficients!
                factor = 2 + (i % 5) # 2 to 6
                offset = 5 + (i * 3) # 5, 8, 11, ...
                x_val = 2 + (i % 8) # 2 to 9
                rhs_val = factor * x_val + offset
                
                cloned["instruction"] = f"Solve for x in the equation: {factor}x + {offset} = {rhs_val}."
                cloned["response"] = f"<think>\n1. Identify linear equation: {factor}x + {offset} = {rhs_val}.\n2. Isolate variable term by subtracting {offset} from both sides: {factor}x = {rhs_val} - {offset}\n   {factor}x = {factor * x_val}\n3. Divide both sides by {factor}: x = {factor * x_val} / {factor} = {x_val}\n4. Verify calculation: {factor} * {x_val} + {offset} = {factor * x_val + offset} (Correct).\n</think>\nTo solve **{factor}x + {offset} = {rhs_val}**:\n\n1. **Subtract {offset}** from both sides:\n   $${factor}x = {rhs_val} - {offset}$$\n   $${factor}x = {factor * x_val}$$\n\n2. **Divide both sides by {factor}**:\n   $$x = \\frac{{ {factor * x_val} }}{{ {factor} }}$$\n   $$x = {x_val}$$\n\n2. **Divide both sides by {factor}**:\n   $$x = \\frac{{ {factor * x_val} }}{{ {factor} }}$$\n   $$x = {x_val}$$\n\nTherefore, **x = {x_val}**."
            elif "palindrome" in t["instruction"]:
                cloned["instruction"] = t["instruction"]
                cloned["response"] = f"<think>\n1. Retrieve programming knowledge: Python palindrome check.\n2. Design strategy: Lowercase and strip non-alphanumeric chars, then use slice reversal `cleaned == cleaned[::-1]`.\n3. Draft standard docstrings, PEP-8 spacing, and example prints.\n</think>\n{t['response_template']}"
            elif "list comprehensions" in t["instruction"]:
                cloned["instruction"] = t["instruction"]
                cloned["response"] = f"<think>\n1. Identify topic: Python list comprehensions.\n2. Explain syntax: expression for item in iterable.\n3. Compare with standard for-loops to highlight readability.\n4. Write clear code examples.\n</think>\n{t['response_template']}"
            elif "self-attention" in t["instruction"]:
                cloned["instruction"] = t["instruction"]
                cloned["response"] = f"<think>\n1. Explain transformer self-attention.\n2. Define Query, Key, and Value role.\n3. Highlight parallel processing compared to sequential models.\n</think>\n{t['response_template']}"
            elif "triangular mask" in t["instruction"]:
                cloned["instruction"] = t["instruction"]
                cloned["response"] = f"<think>\n1. Explain lower triangular causal mask.\n2. Explain -infinity substitution before softmax calculation.\n3. Detail why it is critical for decoder autoregressive limits.\n</think>\n{t['response_template']}"
            else:
                # Conversational
                cloned["instruction"] = t["instruction"]
                cloned["response"] = f"<think>\n1. Persona check: Local AI assistant Geocentric.\n2. Tone: Helpful, humble, professional.\n3. Draft concise response.\n</think>\n{t['response_template']}"
                
            cloned["input"] = ""
            expanded_sft.append(cloned)
            
    sft_path = Path("data/guided_sft_seed.jsonl")
    sft_path.parent.mkdir(parents=True, exist_ok=True)
    with sft_path.open("w", encoding="utf-8") as f:
        for item in expanded_sft:
            f.write(json.dumps(item) + "\n")
            
    print(f"  Created SFT dataset at {sft_path} ({len(expanded_sft)} samples, {len(sft_path.read_text(encoding='utf-8'))} bytes)")
    print("Synthetic datasets prepared perfectly!")

if __name__ == "__main__":
    main()
