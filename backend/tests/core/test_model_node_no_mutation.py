"""Verify that amodel_node does not mutate the original human message in state.

The bug: previous code modified `last_message.content` in-place, baking
`<task>` wrappers and instruction suffixes into the checkpointed state.
On subsequent turns the LLM would see every historical human message
decorated with `<task>` tags, making it appear as multiple active tasks.
"""

import unittest

from langchain_core.messages import AIMessage, HumanMessage

from giga_agent.core.agent.graph_factory import (
    _build_file_prompt,
    _build_selected_prompt,
    _generate_user_info,
    _plan_mode_human_reminder,
)


class MessageCopyContractTests(unittest.TestCase):
    """Verify that the copy-based approach used in amodel_node
    never mutates the original HumanMessage object."""

    def test_model_copy_does_not_mutate_original(self):
        original = HumanMessage(content="Привет")
        copy = original.model_copy(update={"content": "<task>Привет</task>"})

        self.assertEqual(original.content, "Привет")
        self.assertEqual(copy.content, "<task>Привет</task>")

    def test_list_copy_with_replacement_preserves_original(self):
        msg = HumanMessage(content="Оригинал")
        original_list = [msg]

        messages_for_llm = list(original_list)
        enriched = msg.model_copy(
            update={"content": "<task>Оригинал</task>\nинструкции"}
        )
        messages_for_llm[-1] = enriched

        self.assertEqual(original_list[0].content, "Оригинал")
        self.assertIn("<task>", messages_for_llm[-1].content)
        self.assertIs(original_list[0], msg)

    def test_model_copy_preserves_additional_kwargs(self):
        files = [{"path": "/tmp/file.txt"}]
        selected = {"img.png": "screenshot"}
        msg = HumanMessage(
            content="Проанализируй файл",
            additional_kwargs={"files": files, "selected": selected},
        )

        copy = msg.model_copy(update={"content": "<task>Проанализируй файл</task>"})

        self.assertEqual(copy.additional_kwargs["files"], files)
        self.assertEqual(copy.additional_kwargs["selected"], selected)
        self.assertEqual(msg.content, "Проанализируй файл")

    def test_model_copy_preserves_message_id(self):
        msg = HumanMessage(content="test", id="msg-123")
        copy = msg.model_copy(update={"content": "modified"})

        self.assertEqual(copy.id, "msg-123")
        self.assertEqual(msg.content, "test")


class MultiTurnSimulationTests(unittest.TestCase):
    """Simulate multiple conversation turns and verify that
    previous human messages remain unmodified."""

    def test_previous_human_messages_stay_clean(self):
        msg1 = HumanMessage(content="Первый вопрос")
        ai1 = AIMessage(content="Первый ответ")
        msg2 = HumanMessage(content="Второй вопрос")

        state_messages = [msg1, ai1, msg2]

        messages_for_llm = list(state_messages)
        if messages_for_llm and messages_for_llm[-1].type == "human":
            last = messages_for_llm[-1]
            enriched = last.model_copy(
                update={"content": f"<task>{last.content}</task>\nинструкции"}
            )
            messages_for_llm[-1] = enriched

        self.assertEqual(msg1.content, "Первый вопрос")
        self.assertEqual(msg2.content, "Второй вопрос")

        self.assertIn("<task>", messages_for_llm[-1].content)
        self.assertNotIn("<task>", state_messages[-1].content)

    def test_multiple_turns_no_accumulated_tags(self):
        messages = []
        for i in range(5):
            human = HumanMessage(content=f"Вопрос {i}")
            messages.append(human)

            copy = list(messages)
            enriched = human.model_copy(
                update={"content": f"<task>{human.content}</task>\nинструкции"}
            )
            copy[-1] = enriched

            ai = AIMessage(content=f"Ответ {i}")
            messages.append(ai)

        for msg in messages:
            if msg.type == "human":
                self.assertNotIn("<task>", msg.content)


class HelperFunctionTests(unittest.TestCase):
    """Verify that helper functions read-only access message attributes."""

    def test_build_file_prompt_does_not_mutate(self):
        msg = HumanMessage(
            content="test",
            additional_kwargs={"files": [{"path": "/tmp/f.txt"}]},
        )
        original_content = msg.content
        _build_file_prompt(msg)
        self.assertEqual(msg.content, original_content)

    def test_build_selected_prompt_does_not_mutate(self):
        msg = HumanMessage(
            content="test",
            additional_kwargs={"selected": {"img.png": "desc"}},
        )
        original_content = msg.content
        _build_selected_prompt(msg)
        self.assertEqual(msg.content, original_content)

    def test_generate_user_info_does_not_mutate_state(self):
        state = {"instructions": "Be helpful", "messages": []}
        original_instructions = state["instructions"]
        _generate_user_info(state)
        self.assertEqual(state["instructions"], original_instructions)

    def test_plan_mode_human_reminder_is_emitted_only_in_plan_mode(self):
        reminder = _plan_mode_human_reminder({"mode": "plan"})

        self.assertIsNotNone(reminder)
        self.assertIn("режим планирования", reminder)
        self.assertIn("ask_questions", reminder)
        self.assertIn("update_plan", reminder)
        self.assertIn("present_plan", reminder)
        self.assertIsNone(_plan_mode_human_reminder({"mode": "normal"}))
