#!/usr/bin/env python3
"""
Model Router — маршрутизация задач по моделям.
Доступные модели (отдельный API ключ):
  1. xiaomi/mimo-v2.5        — быстрая генерация кода (основная)
  2. xiaomi/mimo-v2.5-pro    — улучшенная версия MiMo
  3. anthropic/claude-sonnet-4.6 — vision, сложные задачи, чертежи
  4. qwen/qwen2.5-vl-72b-instruct — vision, анализ изображений
"""

import logging
import re

log = logging.getLogger("model_router")


# === Модельные профили (только доступные) ===

class ModelProfile:
    def __init__(self, model_id, strengths, max_tokens=4096, supports_vision=False):
        self.model_id = model_id
        self.strengths = strengths
        self.max_tokens = max_tokens
        self.supports_vision = supports_vision


MODELS = {
    "mimo": ModelProfile(
        "xiaomi/mimo-v2.5",
        ["code_generation", "simple_tasks", "text_to_model"],
        max_tokens=4096,
        supports_vision=False,
    ),
    "mimo_pro": ModelProfile(
        "xiaomi/mimo-v2.5-pro",
        ["code_generation", "complex_tasks", "text_to_model"],
        max_tokens=4096,
        supports_vision=False,
    ),
    "claude": ModelProfile(
        "anthropic/claude-sonnet-4.6",
        ["vision", "complex_tasks", "drawing_analysis", "code_review", "multi_step"],
        max_tokens=8192,
        supports_vision=True,
    ),
    "kimi": ModelProfile(
        "moonshotai/kimi-k2.7-code",
        ["vision", "image_comparison", "screenshot_analysis", "ocr"],
        max_tokens=4096,
        supports_vision=True,
    ),
}


# === Классификатор задач ===

DRAWING_KEYWORDS = [
    "чертеж", "чертёж", "проекция", "вид сверху", "вид спереди",
    "вид сбоку", "разрез", "сечение", "скан", "фото",
]

COMPLEX_KEYWORDS = [
    "сборка", "сборку", "составная", "составной",
    "массив", "массивом", "повтори", "скопируй",
    "фаска", "фаску", "скругление", "скругли",
    "вычесть", "вырез", "отверстие",
    "зубчат", "шестерн",
]

VISION_TRIGGERS = [
    "сравни", "проверь", "сверь", "что не так",
    "расхождени", "ошибк",
]


def classify_task(user_message, has_image=False):
    """Классифицировать тип задачи."""
    msg_lower = user_message.lower()
    is_drawing = any(kw in msg_lower for kw in DRAWING_KEYWORDS) or has_image
    is_complex = any(kw in msg_lower for kw in COMPLEX_KEYWORDS)
    needs_vision = any(kw in msg_lower for kw in VISION_TRIGGERS) or has_image

    if is_complex or is_drawing:
        complexity = "complex"
    elif any(w in msg_lower for w in ["просто", "простой", "базов", "создай куб", "создай цилиндр"]):
        complexity = "simple"
    else:
        complexity = "medium"

    task_type = "drawing" if is_drawing else "modeling"
    return task_type, complexity, needs_vision


def select_model(user_message, has_image=False, step_type=None, error_context=False):
    """Выбрать модель для задачи.

    Логика:
    - Визуальная проверка → Claude (vision)
    - Чертеж/изображение → Claude (vision)
    - Сравнение скриншотов → Qwen VL (vision)
    - Сложные задачи → MiMo Pro
    - Простые/средние код → MiMo (быстро)
    """
    task_type, complexity, needs_vision = classify_task(user_message, has_image)

    # Визуальная проверка — Claude (vision, лучший анализ)
    if step_type == "visual_check":
        return "claude", MODELS["claude"], "visual check requires vision"

    # Сравнение скриншотов — Kimi (vision + OCR)
    if step_type == "screenshot_compare":
        return "kimi", MODELS["kimi"], "screenshot comparison with OCR"

    # Ошибки — MiMo Pro (код + анализ)
    if error_context:
        if needs_vision:
            return "claude", MODELS["claude"], "error fix with visual context"
        return "mimo_pro", MODELS["mimo_pro"], "error analysis and fix"

    # Vision с изображением — Claude
    if needs_vision and has_image:
        return "claude", MODELS["claude"], "vision task with image"

    # Сложные задачи — MiMo Pro
    if complexity == "complex":
        return "mimo_pro", MODELS["mimo_pro"], f"complex {task_type}"

    # Vision без картинки — Claude
    if needs_vision:
        return "claude", MODELS["claude"], "vision required"

    # Простые/средние — MiMo (быстро)
    return "mimo", MODELS["mimo"], f"simple/medium {task_type}"


def get_system_prompt_for_model(model_id, base_prompt, task_context=""):
    """Подготовить системный промпт с учётом модели."""
    profile = None
    for m in MODELS.values():
        if m.model_id == model_id:
            profile = m
            break

    prompt = base_prompt

    if profile and profile.supports_vision:
        prompt += """

## VISUAL CHECK (REQUIRED):
After code execution you MUST verify the result:
1. Request screenshot of current view
2. Compare with user's request
3. If differences found - fix and re-check

This is critical. 45% of tasks require fixing after visual inspection.
"""

    if task_context:
        prompt += f"\n\n{task_context}"

    return prompt


# === Промпты для этапов ===

PLAN_PROMPT = """Analyze the request and create a building plan.

Return JSON:
{"action": "plan", "steps": ["step 1: description", "step 2: description", ...]}

Rules:
- Max 10 steps
- Each step = one clear, executable operation with h.* wrapper methods
- For complex operations (arrays, rotations, profiles), break into smaller steps:
  BAD: "Cut29 teeth through rotation"
  GOOD: "Create one tooth profile shape" then "Duplicate tooth around center using loop"
- Each step must be completable with a single code block
- Always end with: "Check results with h.list_objects() and h.info()"
"""

CODE_WITH_PLAN_PROMPT = """Execute the current plan step. Code must be self-contained.

Context:
- Previous steps already executed (objects exist in document)
- Use h.list_objects() to see current state
- Reference objects by name from previous steps

Return JSON:
{"action": "code", "description": "step description", "code": "Python code using h.*"}

IMPORTANT:
- Use wrapper API (h.box, h.cylinder, h.fuse, h.cut etc.)
- Save each object to a variable with descriptive name
"""
