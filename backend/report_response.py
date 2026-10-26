"""Closable WSGI file iterator, including disconnect before the first read."""
class FileChunks:
    def __init__(self,stream):self.stream=stream
    def __iter__(self):return self
    def __next__(self):
        if self.stream.closed:raise StopIteration
        try:data=self.stream.read(65536)
        except Exception:
            self.close()
            raise
        if not data:
            self.close()
            raise StopIteration
        return data
    def close(self):self.stream.close()
