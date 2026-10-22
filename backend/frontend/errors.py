# frontend/errors.py - errors shared by the C front end.


class SemanticError(Exception):
    """A type or scope error found by the semantic analyser."""

    def __init__(self, line, col, msg):
        self.line = line
        self.col = col
        self.msg = msg
        super().__init__("%d:%d: %s" % (line, col, msg))


class UnsupportedFeatureError(SemanticError):
    """A construct the front end knows about but does not implement."""

    def __init__(self, feature, line, col):
        self.feature = feature
        super().__init__(line, col, "unsupported: %s" % feature)
