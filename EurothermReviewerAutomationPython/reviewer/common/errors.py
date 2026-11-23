"""Structured workflow failures."""



class WorkflowError(RuntimeError):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code, self.details = code, details
