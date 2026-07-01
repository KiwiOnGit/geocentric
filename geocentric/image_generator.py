import os
import torch
from diffusers import StableDiffusionPipeline

_pipeline = None
_current_model_id = None

IMAGE_STYLE_PRESETS = {
    "fast": {
        "label": "Fast Concept",
        "model_id": "stabilityai/sd-turbo",
        "prompt_suffix": "clean concept art, crisp shapes, fast draft, readable composition",
    },
    "photo": {
        "label": "Cinematic Photo",
        "model_id": "stabilityai/sd-turbo",
        "prompt_suffix": "photorealistic cinematic lighting, detailed texture, natural lens, dramatic composition",
    },
    "anime": {
        "label": "Anime Illustration",
        "model_id": "stabilityai/sd-turbo",
        "prompt_suffix": "polished anime illustration, expressive lighting, clean linework, vivid color",
    },
    "fantasy": {
        "label": "Fantasy Painting",
        "model_id": "stabilityai/sd-turbo",
        "prompt_suffix": "epic fantasy digital painting, painterly brushwork, rich atmosphere, highly detailed",
    },
}

IMAGE_QUALITY_PRESETS = {
    "draft": {"steps": 1, "scale": 1.0},
    "standard": {"steps": 4, "scale": 1.0},
    "high": {"steps": 8, "scale": 1.0},
    "ultra": {"steps": 12, "scale": 1.25},
}


def image_style_options():
    return [
        {"id": key, "label": value["label"], "model_id": value["model_id"]}
        for key, value in IMAGE_STYLE_PRESETS.items()
    ]


def resolve_image_options(style: str = "fast", quality: str = "standard"):
    style_key = (style or "fast").strip().lower()
    quality_key = (quality or "standard").strip().lower()
    style_cfg = IMAGE_STYLE_PRESETS.get(style_key, IMAGE_STYLE_PRESETS["fast"])
    quality_cfg = IMAGE_QUALITY_PRESETS.get(quality_key, IMAGE_QUALITY_PRESETS["standard"])
    return style_key if style_key in IMAGE_STYLE_PRESETS else "fast", quality_key if quality_key in IMAGE_QUALITY_PRESETS else "standard", style_cfg, quality_cfg

def get_pipeline(model_id: str = "stabilityai/sd-turbo"):
    """
    Loads and caches the Stable Diffusion pipeline on-device.
    Supports CUDA (Windows/Linux), MPS (macOS), and CPU.
    """
    global _pipeline, _current_model_id
    if _pipeline is not None and _current_model_id == model_id:
        return _pipeline

    # If another model was loaded, delete it to save memory
    if _pipeline is not None:
        del _pipeline
        _pipeline = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        elif torch.backends.mps.is_available():
            torch.mps.empty_cache()

    # Determine device
    if torch.cuda.is_available():
        device = "cuda"
        dtype = torch.float16
    elif torch.backends.mps.is_available():
        device = "mps"
        dtype = torch.float16
    else:
        device = "cpu"
        dtype = torch.float32

    print(f"[IMAGE GENERATOR] Loading {model_id} on device: {device} ({dtype})")
    
    try:
        # Load pipeline
        pipe = StableDiffusionPipeline.from_pretrained(
            model_id,
            torch_dtype=dtype,
            use_safetensors=True
        )
        
        # Disable safety checker to fit in consumer memory (16GB RAM/VRAM)
        if hasattr(pipe, "safety_checker") and pipe.safety_checker is not None:
            pipe.safety_checker = None
            
        pipe = pipe.to(device)
        
        # Optional: enable attention slicing or CPU offload if on a lower memory device
        if device == "cpu":
            pipe.enable_attention_slicing()
        
        _pipeline = pipe
        _current_model_id = model_id
        print(f"[IMAGE GENERATOR] Pipeline loaded successfully on {device}.")
    except Exception as e:
        print(f"[IMAGE GENERATOR] Error loading pipeline: {e}")
        # Fallback to float32 on CPU
        pipe = StableDiffusionPipeline.from_pretrained(
            model_id,
            torch_dtype=torch.float32,
            use_safetensors=True
        )
        pipe.safety_checker = None
        pipe = pipe.to("cpu")
        _pipeline = pipe
        _current_model_id = model_id
        print("[IMAGE GENERATOR] Fallback pipeline loaded on CPU (float32).")

    return _pipeline

def generate_image_local(
    prompt: str,
    num_inference_steps: int = 4,
    width: int = 512,
    height: int = 512,
    callback=None,
    model_id: str = "stabilityai/sd-turbo",
    style: str = "fast"
):
    """
    Generates an image from a prompt.
    callback is a function: callback(step_index: int, total_steps: int)
    """
    _, _, style_cfg, _ = resolve_image_options(style, "standard")
    model_id = model_id or style_cfg["model_id"]
    styled_prompt = prompt
    suffix = style_cfg.get("prompt_suffix", "")
    if suffix and suffix.lower() not in styled_prompt.lower():
        styled_prompt = f"{prompt}, {suffix}"

    pipe = get_pipeline(model_id)
    
    # Define inner callback for diffusers
    def diffusers_callback(step: int, timestep: int, latents: torch.FloatTensor):
        if callback:
            # step is 0-indexed in diffusers
            callback(step + 1, num_inference_steps)

    # sd-turbo works best with guidance_scale=0.0 or 1.0 (recommended 0.0)
    guidance_scale = 0.0 if "turbo" in getattr(pipe, "config", {}).get("_class_name", "").lower() or "turbo" in str(pipe.config) else 7.5
    
    print(f"[IMAGE GENERATOR] Generating image with prompt: '{styled_prompt}' (steps: {num_inference_steps}, size: {width}x{height}, model: {model_id}, style: {style})")
    
    result = pipe(
        prompt=styled_prompt,
        num_inference_steps=num_inference_steps,
        guidance_scale=guidance_scale,
        width=width,
        height=height,
        callback=diffusers_callback,
        callback_steps=1
    )
    
    # Cleanup memory
    if torch.backends.mps.is_available():
        torch.mps.empty_cache()
    elif torch.cuda.is_available():
        torch.cuda.empty_cache()
        
    return result.images[0]
