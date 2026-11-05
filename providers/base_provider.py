from abc import ABC, abstractmethod

class BaseProvider(ABC):

    @abstractmethod
    def send_message(self, messages, model):
        pass

    @abstractmethod
    def test_connection(self, model):
        pass
