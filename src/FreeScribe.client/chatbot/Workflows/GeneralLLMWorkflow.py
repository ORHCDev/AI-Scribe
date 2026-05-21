from chatbot.Workflows.Workflow import Workflow, WorkflowContext, WorkflowResult, workflow

@workflow(
    name="general_llm",
    description="General medical knowledge questions that do not require patient-specific data",
    keywords=["explain", "summarize", "define"]
)
class GeneralLLMWorkflow(Workflow):

    def run(self, user_input: str, context: WorkflowContext) -> WorkflowResult:
        """
        Single LLM call with conversation history. No patient context or tools.
        """
        history = '\n'.join(context.conversation_history) if context.conversation_history else "None"
        prompt = context.prompts.get("general_prompt").format(
            history=history,
            user_input=user_input
        )
        #print(f"{'='*50}\nGENERAL LLM PROMPT:\n{prompt}\n{'='*50}")
        resp = context.ai_conn.send_message(prompt)
        return WorkflowResult(response=resp)
