"""
Shared instructions added to every prompt that turns a visit transcript into a note.

Whisper returns one block of text with no speaker labels, so the note model cannot see who said
what. Without guidance it may write the patient's own statements ("I stopped my aspirin",
"I think it's my heart") as the physician's findings or plan. These rules are appended in code so
they apply whichever prompt is selected (including user-defined prompts in prompts/prompts.yaml).
"""

TRANSCRIPT_SPEAKER_RULES = """SPEAKER ATTRIBUTION (important):
If the input contains a conversation transcript, it is a single block of speech-to-text with NO speaker
labels: the physician, the patient and sometimes a family member are mixed together. Work out who is
speaking from context and follow these rules:
- Statements in the first person about symptoms, history, habits, medications taken or stopped, or the
  speaker's own beliefs and worries (e.g. "I have chest pain", "I stopped my aspirin", "I think it's my
  heart") come from the patient or a family member. Write them as patient-reported, e.g. "The patient
  reported ...", "The patient stated that he had stopped ...". Never present them as the physician's
  findings, examination or decisions.
- The patient's own interpretations or guesses are not a diagnosis; do not state them as findings in the
  impression/assessment.
- Only include in the PLAN decisions the physician explicitly made or instructed during this visit
  (medications started, stopped or changed, tests ordered, referrals, follow-up). A patient's question,
  request or self-reported change is not a plan item; if the patient changed or stopped a medication on
  their own, record it in the history as patient-reported.
- If it is unclear who said something, treat it as information reported by the patient rather than as
  the physician's statement or decision."""


def with_speaker_rules(prompt: str) -> str:
    """`prompt` followed by the transcript speaker-attribution rules."""
    return f"{str(prompt or '').rstrip()}\n\n{TRANSCRIPT_SPEAKER_RULES}"
