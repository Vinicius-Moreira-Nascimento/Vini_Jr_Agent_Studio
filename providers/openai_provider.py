from openai import OpenAI
from providers.base_provider import BaseProvider

class OpenAIProvider(BaseProvider):

    def __init__(self, api_key):
        self.client = OpenAI(api_key=api_key)

    def send_message(self, messages, model):

        response = self.client.responses.create(
            model=model,
            input=messages
        )

        return response.output_text

    def stream_message(self, messages, model):
        """
        Transmite incrementalmente o texto da Responses API.

        Gera somente os deltas de texto.
        Exige o evento response.completed para considerar
        a resposta concluída com sucesso.
        """

        stream = self.client.responses.create(
            model=model,
            input=messages,
            stream=True
        )

        completed = False

        for event in stream:
            event_type = getattr(event, "type", "")

            if event_type == "response.output_text.delta":
                delta = getattr(event, "delta", "")

                if delta:
                    yield delta

            elif event_type == "response.completed":
                completed = True

            elif event_type in (
                "response.failed",
                "response.incomplete",
                "error"
            ):
                response = getattr(event, "response", None)
                error = getattr(response, "error", None)

                message = (
                    getattr(error, "message", None)
                    or getattr(event, "message", None)
                    or getattr(event, "type", "Erro no streaming")
                )

                if event_type == "response.incomplete":
                    incomplete = getattr(
                        response,
                        "incomplete_details",
                        None
                    )

                    reason = getattr(incomplete, "reason", None)

                    if reason:
                        message = f"{message} ({reason})"

                raise RuntimeError(str(message))

        if not completed:
            raise RuntimeError(
                "O streaming terminou sem receber response.completed."
            )

    def test_connection(self, model):

        response = self.client.responses.create(
            model=model,
            input="Responda apenas: CONEXAO VINI_JR OK"
        )

        return response.output_text
