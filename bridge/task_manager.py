#!/usr/bin/env python3
"""
Task Manager — память задач, ReAct-цикл, прогресс.
Хранит контекст задачи между запросами, логирует каждый шаг.
"""

import time
import json
import uuid
import threading
import logging

log = logging.getLogger("task_manager")


class Step:
    """Один шаг задачи."""
    def __init__(self, step_id, description):
        self.step_id = step_id
        self.description = description
        self.status = "pending"  # pending | running | success | error | skipped
        self.code = None
        self.output = None
        self.error = None
        self.screenshot_path = None
        self.visual_match = None  # True/False/None (результат визуальной проверки)
        self.started_at = None
        self.completed_at = None
        self.model_used = None
        self.retry_count = 0

    def to_dict(self):
        return {
            "step_id": self.step_id,
            "description": self.description,
            "status": self.status,
            "code": self.code,
            "output": self.output,
            "error": self.error,
            "screenshot_path": self.screenshot_path,
            "visual_match": self.visual_match,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "model_used": self.model_used,
            "retry_count": self.retry_count,
        }


class Task:
    """Одна задача (может содержать несколько шагов)."""
    def __init__(self, task_id, user_request):
        self.task_id = task_id
        self.user_request = user_request
        self.steps = []
        self.status = "active"  # active | completed | error | cancelled
        self.created_at = time.time()
        self.updated_at = time.time()
        self.plan = None  # план от модели (список описаний шагов)
        self.final_result = None
        self.error_log = []  # все ошибки на протяжении задачи
        self.objects_snapshot = []  # состояние документа после последнего шага

    def add_step(self, description):
        step = Step(f"step_{len(self.steps) + 1}", description)
        self.steps.append(step)
        self.updated_at = time.time()
        return step

    def current_step(self):
        for s in self.steps:
            if s.status in ("pending", "running"):
                return s
        return None

    def completed_steps(self):
        return [s for s in self.steps if s.status == "success"]

    def failed_steps(self):
        return [s for s in self.steps if s.status == "error"]

    def progress_pct(self):
        if not self.steps:
            return 0
        done = len(self.completed_steps())
        return int((done / len(self.steps)) * 100)

    def to_dict(self):
        return {
            "task_id": self.task_id,
            "user_request": self.user_request,
            "status": self.status,
            "plan": self.plan,
            "steps": [s.to_dict() for s in self.steps],
            "progress_pct": self.progress_pct(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "final_result": self.final_result,
            "error_count": len(self.error_log),
            "objects_count": len(self.objects_snapshot),
        }


class TaskManager:
    """Менеджер задач с TTL-очисткой."""

    def __init__(self, ttl_seconds=3600, max_tasks=50):
        self._tasks = {}  # task_id -> Task
        self._lock = threading.Lock()
        self._ttl = ttl_seconds
        self._max_tasks = max_tasks
        # Запуск cleanup в фоне
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleanup_thread.start()

    def create_task(self, user_request):
        """Создать новую задачу."""
        task_id = str(uuid.uuid4())[:8]
        task = Task(task_id, user_request)
        with self._lock:
            self._tasks[task_id] = task
            # Очистка если много задач
            if len(self._tasks) > self._max_tasks:
                oldest = min(self._tasks.values(), key=lambda t: t.created_at)
                del self._tasks[oldest.task_id]
        log.info(f"Task created: {task_id} — {user_request[:80]}")
        return task

    def get_task(self, task_id):
        """Получить задачу по ID."""
        with self._lock:
            return self._tasks.get(task_id)

    def get_or_create_recent(self, user_request, max_age=300):
        """Получить последнюю активную задачу или создать новую.
        max_age — максимальный возраст в секундах для переиспользования."""
        with self._lock:
            active = [t for t in self._tasks.values()
                      if t.status == "active"
                      and (time.time() - t.updated_at) < max_age]
            if active:
                task = max(active, key=lambda t: t.updated_at)
                log.info(f"Reusing task: {task.task_id}")
                return task
        return self.create_task(user_request)

    def build_task_context(self, task):
        """Построить контекст задачи для передачи модели."""
        if not task:
            return ""

        lines = [f"## Текущая задача: {task.user_request[:200]}"]
        lines.append(f"Статус: {task.status} | Шагов: {len(task.steps)} | Прогресс: {task.progress_pct()}%")

        if task.plan:
            lines.append("\n### План:")
            for i, step_desc in enumerate(task.plan, 1):
                step_obj = task.steps[i - 1] if i <= len(task.steps) else None
                status_icon = "✅" if step_obj and step_obj.status == "success" else \
                              "❌" if step_obj and step_obj.status == "error" else \
                              "🔄" if step_obj and step_obj.status == "running" else \
                              "⏳"
                lines.append(f"  {status_icon} Шаг {i}: {step_desc}")

        # Последние шаги с деталями
        recent_steps = task.steps[-3:] if len(task.steps) > 3 else task.steps
        if recent_steps:
            lines.append("\n### Последние шаги:")
            for s in recent_steps:
                lines.append(f"  [{s.status}] {s.description}")
                if s.error:
                    lines.append(f"    Ошибка: {s.error[:200]}")
                if s.output:
                    lines.append(f"    Вывод: {s.output[:200]}")

        # Ошибки
        if task.error_log:
            lines.append(f"\n### Всего ошибок: {len(task.error_log)}")
            last_err = task.error_log[-1]
            lines.append(f"  Последняя: {last_err[:300]}")

        return "\n".join(lines)

    def build_error_feedback(self, task, error_output, fc_logs=""):
        """Построить фидбек об ошибке для модели."""
        lines = [
            "## ОШИБКА В ПРЕДЫДУЩЕМ ШАГЕ",
            f"Задача: {task.user_request[:150]}",
            f"Текущий шаг: {task.current_step().description if task.current_step() else 'N/A'}",
            f"\nОшибка выполнения:\n```\n{error_output[:1000]}\n```",
        ]
        if fc_logs:
            lines.append(f"\nFreeCAD логи:\n```\n{fc_logs[:500]}\n```")
        lines.append("\nПожалуйста, исправь код и повтори. Учти ошибку при генерации нового кода.")
        return "\n".join(lines)

    def build_visual_feedback(self, task, screenshot_b64, match_result, differences=None):
        """Построить фидбек по визуальному сравнению."""
        lines = [
            "## ВИЗУАЛЬНАЯ ПРОВЕРКА",
            f"Результат сравнения: {'✅ Совпадает' if match_result else '❌ Расхождение'}",
        ]
        if differences:
            lines.append("Расхождения:")
            for d in differences:
                lines.append(f"  - {d}")
        lines.append("\nЕсли есть расхождения — исправь код и повтори шаг.")
        return "\n".join(lines)

    def _cleanup_loop(self):
        """Очистка старых задач по TTL."""
        while True:
            time.sleep(60)
            now = time.time()
            with self._lock:
                expired = [tid for tid, t in self._tasks.items()
                           if (now - t.updated_at) > self._ttl]
                for tid in expired:
                    del self._tasks[tid]
                    log.info(f"Task expired: {tid}")

    def stats(self):
        with self._lock:
            return {
                "total": len(self._tasks),
                "active": sum(1 for t in self._tasks.values() if t.status == "active"),
                "completed": sum(1 for t in self._tasks.values() if t.status == "completed"),
            }
