import base64
import io
import json
import os
import sys
import time
from pathlib import Path

import replicate
from dotenv import load_dotenv
from PIL import Image

load_dotenv()

# Paths to the template images
TEMPLATE_PATHS = [
    Path(__file__).parent / "Steve_template.png",
    Path(__file__).parent / "Template_classic.png",
    Path(__file__).parent / "jesus_template.png",
]

# Output folders for generated skins
OUTPUT_DIR = Path(__file__).parent / "skins"
RAW_OUTPUT_DIR = Path(__file__).parent / "skins_raw"

# Chroma key color - bright magenta that's unlikely to be in actual skin designs
CHROMA_KEY = (255, 0, 255)  # #FF00FF
TOLERANCE = 30  # Color matching tolerance


def prepare_template(template_path: Path) -> str:
    """Load template, upscale to 1024x1024, add chroma key background, return as data URI."""
    with Image.open(template_path) as img:
        img = img.convert("RGBA")

        # Create new image with chroma key background
        bg = Image.new("RGBA", img.size, (*CHROMA_KEY, 255))
        # Paste template on top (using alpha as mask)
        bg.paste(img, (0, 0), img)

        # Upscale to 1024x1024 using nearest neighbor to preserve pixel art
        upscaled = bg.resize((1024, 1024), Image.Resampling.NEAREST)

        # Save to bytes and encode as base64
        buffer = io.BytesIO()
        upscaled.save(buffer, format="PNG")
        template_data = base64.b64encode(buffer.getvalue()).decode("utf-8")
        return f"data:image/png;base64,{template_data}"


def prepare_all_templates() -> list[str]:
    """Prepare all template images and return as list of data URIs."""
    return [prepare_template(path) for path in TEMPLATE_PATHS]


def remove_chroma_key(img: Image.Image) -> Image.Image:
    """Replace chroma key color with transparency."""
    img = img.convert("RGBA")
    pixels = img.load()

    for y in range(img.height):
        for x in range(img.width):
            r, g, b, a = pixels[x, y]
            # Check if pixel is close to chroma key color
            if (
                abs(r - CHROMA_KEY[0]) < TOLERANCE
                and abs(g - CHROMA_KEY[1]) < TOLERANCE
                and abs(b - CHROMA_KEY[2]) < TOLERANCE
            ):
                pixels[x, y] = (0, 0, 0, 0)  # Fully transparent

    return img


def clear_overlay_layer(img: Image.Image, mode: str = "none") -> Image.Image:
    """
    Clear overlay/second layer areas based on mode.

    Modes:
        - "none": Remove all overlay layers (base skin only)
        - "head": Keep only head overlay (hat), remove body/arms/legs overlays
        - "all": Keep all overlay layers
    """
    if mode == "all":
        return img

    img = img.convert("RGBA")
    pixels = img.load()

    # Overlay layer regions (x, y, width, height) for 64x64 skin:
    hat_region = (32, 0, 32, 16)  # Hat (head overlay)
    body_overlay_regions = [
        (16, 32, 24, 16),  # Body overlay
        (40, 32, 16, 16),  # Right arm overlay
        (48, 48, 16, 16),  # Left arm overlay
        (0, 32, 16, 16),  # Right leg overlay
        (0, 48, 16, 16),  # Left leg overlay
    ]

    # Determine which regions to clear
    if mode == "none":
        regions_to_clear = [hat_region] + body_overlay_regions
    elif mode == "head":
        regions_to_clear = body_overlay_regions
    else:
        regions_to_clear = []

    for rx, ry, rw, rh in regions_to_clear:
        for y in range(ry, ry + rh):
            for x in range(rx, rx + rw):
                if 0 <= x < img.width and 0 <= y < img.height:
                    pixels[x, y] = (0, 0, 0, 0)

    return img


def generate_skin(
    prompt: str, output_path: str = "skin.png", overlay_mode: str = "none"
) -> str:
    """Generate a Minecraft skin based on the given prompt."""

    # Determine which layers are enabled based on overlay mode
    if overlay_mode == "all":
        layers = {
            "base_layer": "enabled (head, body, arms, legs)",
            "overlay_layer": "enabled (hat, body overlay, arm overlays, leg overlays)",
        }
    elif overlay_mode == "head":
        layers = {
            "base_layer": "enabled (head, body, arms, legs)",
            "overlay_layer": "hat only (body/arm/leg overlays disabled)",
        }
    else:  # none
        layers = {
            "base_layer": "enabled (head, body, arms, legs)",
            "overlay_layer": "disabled (no overlays)",
        }

    prompt_data = {
        "type": "Minecraft skin texture file",
        "resolution": "64x64 pixels",
        "subject": prompt,
        "reference": "Use the provided template image as a reference for the layout",
        "layers": layers,
        "style": {
            "type": "pixel art",
            "detail": "highly detailed",
            "shading": "realistic shading with lighting highlights and depth",
            "textures": "rich textures with subtle color gradients",
        },
        "background": {
            "color": "#FF00FF",
            "type": "solid magenta",
        },
        "edges": "clean",
    }
    full_prompt = json.dumps(prompt_data, indent=2)

    # Prepare all templates (upscale and add chroma key background)
    template_uris = prepare_all_templates()

    print(f"🎨 Generating skin: {prompt}")
    print(f"\n📝 Prompt:\n{full_prompt}\n")
    print("⏳ Please wait...")

    output = replicate.run(
        "google/nano-banana-pro",
        input={
            "prompt": full_prompt,
            "resolution": "1K",
            "image_input": template_uris,
            "aspect_ratio": "1:1",
            "output_format": "png",
            "safety_filter_level": "block_only_high",
        },
    )

    # Download the generated image
    temp_path = "temp_skin.png"
    with open(temp_path, "wb") as file:
        file.write(output.read())

    # Save raw generation to raw folder
    RAW_OUTPUT_DIR.mkdir(exist_ok=True)
    raw_output_path = RAW_OUTPUT_DIR / Path(output_path).name
    with Image.open(temp_path) as img:
        img.save(raw_output_path, "PNG")
    print(f"📁 Raw saved to: {raw_output_path}")

    # Remove chroma key background and resize
    print("🔧 Removing background...")
    with Image.open(temp_path) as img:
        img_transparent = remove_chroma_key(img)
        resized = img_transparent.resize((64, 64), Image.Resampling.NEAREST)
        # Clear the overlay layer based on mode
        final = clear_overlay_layer(resized, overlay_mode)
        final.save(output_path, "PNG")

    # Clean up temp file
    os.remove(temp_path)

    print(f"✅ Skin saved to: {output_path}")
    return output_path


def main():
    print("🧱 Minecraft Skin Generator")
    print("=" * 40)

    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
    else:
        prompt = input("Enter skin description: ").strip()

    if not prompt:
        print("❌ Error: Please provide a description for your skin.")
        sys.exit(1)

    # Ask about overlay layer mode
    print("\nOverlay layer options:")
    print("  1. Remove all (base skin only)")
    print("  2. Keep head only (hat)")
    print("  3. Keep all overlays")
    overlay_choice = input("Choose overlay mode [1/2/3] (default: 1): ").strip()

    overlay_mode = {
        "1": "none",
        "2": "head",
        "3": "all",
    }.get(overlay_choice, "none")

    # Ensure output directory exists
    OUTPUT_DIR.mkdir(exist_ok=True)

    # Generate filename with timestamp (base36 for shorter format) and prompt
    # Base36 timestamp gives ~6 chars and sorts chronologically
    timestamp = base36_encode(int(time.time()))
    safe_name = "".join(c if c.isalnum() or c in " -_" else "" for c in prompt)
    safe_name = safe_name.replace(" ", "_")[:20].strip("_")
    output_path = OUTPUT_DIR / f"{timestamp}_{safe_name}.png"

    generate_skin(prompt, str(output_path), overlay_mode)


def base36_encode(num: int) -> str:
    """Encode a number in base36 (0-9, a-z)."""
    chars = "0123456789abcdefghijklmnopqrstuvwxyz"
    if num == 0:
        return "0"
    result = ""
    while num:
        result = chars[num % 36] + result
        num //= 36
    return result


if __name__ == "__main__":
    main()
