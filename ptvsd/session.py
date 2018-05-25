from .socket import is_socket, close_socket
from .wrapper import VSCodeMessageProcessor
from ._util import Closeable, Startable, debug


class DebugSession(Startable, Closeable):
    """A single DAP session for a network client socket."""

    NAME = 'debug session'
    FAIL_ON_ALREADY_CLOSED = False
    FAIL_ON_ALREADY_STOPPED = False

    @classmethod
    def from_raw(cls, raw, **kwargs):
        """Return a session for the given data."""
        if isinstance(raw, cls):
            return raw
        if not is_socket(raw):
            # TODO: Create a new client socket from a remote address?
            #addr = Address.from_raw(raw)
            raise NotImplementedError
        client = raw
        return cls(client, **kwargs)

    @classmethod
    def from_server_socket(cls, server, **kwargs):
        """Return a session for the next connection to the given socket."""
        client, _ = server.accept()
        return cls(client, ownsock=True, **kwargs)

    def __init__(self, sock, notify_closing=None, ownsock=False):
        super(DebugSession, self).__init__()

        self._sock = sock
        if ownsock:
            def handle_closing(before):
                if before:
                    return
                close_socket(self._sock)
            self.add_close_handler(handle_closing)

        self._killrequested = False
        if notify_closing is not None:
            def handle_closing(before):
                if not before:
                    return
                notify_closing(kill=self._killrequested)
            self.add_close_handler(handle_closing)

        self._msgprocessor = None

    @property
    def socket(self):
        return self._sock

    @property
    def msgprocessor(self):
        return self._msgprocessor

    def handle_pydevd_message(self, cmdid, seq, text):
        if self._msgprocessor is None:
            # TODO: Do more than ignore?
            return
        return self._msgprocessor.on_pydevd_event(cmdid, seq, text)

    def re_build_breakpoints(self):
        """Restore the breakpoints to their last values."""
        if self._msgprocessor is None:
            return
        return self._msgprocessor.re_build_breakpoints()

    def wait_options(self):
        """Return (normal, abnormal) based on the session's launch config."""
        if self._msgprocessor is None:
            return (False, False)
        return self._msgprocessor._wait_options()

    def wait_until_stopped(self):
        """Block until all resources (e.g. message processor) have stopped."""
        if self._msgprocessor is None:
            return
        # TODO: Do this in VSCodeMessageProcessor.close()?
        self._msgprocessor._wait_for_server_thread()

    # internal methods

    def _start(self, threadname, pydevd_notify, pydevd_request, timeout=None):
        """Start the message handling for the session.

        A VSC message loop is started.
        """
        self._msgprocessor = VSCodeMessageProcessor(
            self._sock,
            pydevd_notify,
            pydevd_request,
            notify_disconnecting=self._handle_vsc_disconnect,
            notify_closing=self._handle_vsc_close,
            timeout=timeout,
        )
        self.add_resource_to_close(self._msgprocessor)
        self._msgprocessor.start(threadname)
        return self._msgprocessor_running

    def _stop(self, exitcode=None):
        if self._msgprocessor is None:
            return

        # TODO: This is not correct in the "attach" case.
        self._msgprocessor.handle_session_stopped(exitcode)
        self._msgprocessor.close()
        self._msgprocessor = None

    def _close(self):
        debug('session closing')
        pass

    def _msgprocessor_running(self):
        if self._msgprocessor is None:
            return False
        # TODO: Return self._msgprocessor.is_running().
        return True

    # internal methods for VSCodeMessageProcessor

    def _handle_vsc_disconnect(self, kill=False):
        if kill:
            self._killrequested = kill
        self.close()

    def _handle_vsc_close(self):
        debug('processor closing')
        self.close()