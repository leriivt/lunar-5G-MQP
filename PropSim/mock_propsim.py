#!/usr/bin/env python3
"""
Mock PROPSIM ATE server for testing scripts without hardware.

It listens on a TCP port (default 3334, like the real ATE LAN interface), reads
newline-terminated SCPI commands, keeps a small emulation state machine
(CLOSED -> STOPPED/RUNNING/EDITING) and an error queue, and answers the way the
PROPSIM user reference (chapter 18) describes. It is NOT the real device: only
the commands listed in COMMANDS exist, and timing, limits and most behaviour
are simplified guesses.

    python mock_propsim.py                  # listen on 127.0.0.1:3334
    python mock_propsim.py --slow 3         # opening/closing takes 3 s (tests *OPC? waits)
    python mock_propsim.py --known-file "e:\\1to1 class.smu"   # only these files "exist"

Then point your script at 127.0.0.1.
"""
import argparse
import socketserver
import threading
import time

IDN = "Mock Keysight,PROPSIM F64 (mock),MOCK0001,0.1"
ERR_CMD = '-100,"Command error;ATE command not supported"'
ERR_STATE = '-200,"Execution error;Wrong device state for command"'


class ExecError(Exception):
    pass


def forms(segment):
    """SCPI accepts the short form (capital letters) or the long form of each part."""
    short = "".join(c for c in segment if c.isupper() or c in "*0123456789").lower()
    return short, segment.lower()


class Emulator:
    def __init__(self, slow=0.0, known_files=None):
        self.slow = slow
        self.known_files = known_files or []
        self.lock = threading.Lock()
        self.state = "CLOSED"
        self.file = ""
        self.errors = []
        self.esr_opc = False
        self.values = {}  # (setting, channel) -> value

    # ---- helpers --------------------------------------------------------
    def push_error(self, text):
        if len(self.errors) >= 100:
            self.errors[-1] = '-350,"Queue overflow"'
        else:
            self.errors.append(text)

    def need_open(self):
        if self.state == "CLOSED":
            raise ExecError

    def set_value(self, name, args, cast=float):
        self.need_open()
        if len(args) != 2:
            raise ExecError
        self.values[(name, args[0].strip())] = cast(args[1])

    def get_value(self, name, args, default):
        self.need_open()
        if len(args) != 1:
            raise ExecError
        return str(self.values.get((name, args[0].strip()), default))

    # ---- command implementations -----------------------------------------
    def c_idn(self, a):
        return IDN

    def c_rst(self, a):
        self.state, self.file = "CLOSED", ""
        self.values.clear()

    def c_cls(self, a):
        self.errors.clear()
        self.esr_opc = False

    def c_opc(self, a):
        self.esr_opc = True

    def c_opcq(self, a):
        return "1"

    def c_esrq(self, a):
        value, self.esr_opc = (1 if self.esr_opc else 0), False
        return str(value)

    def c_errq(self, a):
        return self.errors.pop(0) if self.errors else '0,"No error"'

    def c_versq(self, a):
        return "1999.0"

    def c_file(self, a):
        path = ",".join(a).strip()
        if not path or (self.known_files and path not in self.known_files):
            raise ExecError
        time.sleep(self.slow)
        self.state, self.file = "STOPPED", path

    def c_edit(self, a):
        self.c_file(a)
        self.state = "EDITING"

    def c_connect(self, a):
        if self.state != "EDITING":
            raise ExecError
        time.sleep(self.slow)
        self.state = "STOPPED"

    def c_go(self, a):
        if self.state not in ("STOPPED", "RUNNING"):
            raise ExecError
        self.state = "RUNNING"

    def c_stop(self, a):
        if self.state not in ("STOPPED", "RUNNING"):
            raise ExecError
        self.state = "STOPPED"

    def c_close(self, a):
        self.need_open()
        time.sleep(self.slow)
        self.state, self.file = "CLOSED", ""

    def c_stateq(self, a):
        return self.state

    def c_curq(self, a):
        return self.file

    def c_inp_en(self, a):
        self.set_value("inp_en", a, int)

    def c_inp_enq(self, a):
        return self.get_value("inp_en", a, 1)

    def c_inp_lev(self, a):
        self.set_value("inp_lev", a)

    def c_inp_levq(self, a):
        return self.get_value("inp_lev", a, -20)

    def c_out_en(self, a):
        self.set_value("out_en", a, int)

    def c_out_enq(self, a):
        return self.get_value("out_en", a, 1)

    def c_out_gain(self, a):
        self.set_value("out_gain", a)

    def c_out_gainq(self, a):
        return self.get_value("out_gain", a, 0)

    def c_cent(self, a):
        self.set_value("cent", a)

    def c_centq(self, a):
        return self.get_value("cent", a, 2140)

    # ---- dispatch -----------------------------------------------------------
    def table(self):
        t = [
            ("*IDN", True, self.c_idn), ("*RST", False, self.c_rst),
            ("*CLS", False, self.c_cls), ("*OPC", False, self.c_opc),
            ("*OPC", True, self.c_opcq), ("*ESR", True, self.c_esrq),
            ("*WAI", False, lambda a: None),
            ("SYSTem:ERRor", True, self.c_errq), ("SYSTem:VERSion", True, self.c_versq),
            ("SYSTem:RESet", False, self.c_rst),
            ("CALCulate:FILTer:FILE", False, self.c_file),
            ("CALCulate:FILTer:EDIT", False, self.c_edit),
            ("CALCulate:FILTer:CONNECT", False, self.c_connect),
            ("CALCulate:FILTer:CENTer:CH", False, self.c_cent),
            ("CALCulate:FILTer:CENTer:CH", True, self.c_centq),
            ("DIAGnostic:SIMUlation:GO", False, self.c_go),
            ("DIAGnostic:SIMUlation:STOP", False, self.c_stop),
            ("DIAGnostic:SIMUlation:GOStart", False, self.c_stop),
            ("DIAGnostic:SIMUlation:CONTinue", False, self.c_go),
            ("DIAGnostic:SIMUlation:CLOSE", False, self.c_close),
            ("DIAGnostic:SIMUlation:STATE", True, self.c_stateq),
            ("MEM:CURRENT", True, self.c_curq),
            ("INPut:ENable", False, self.c_inp_en), ("INPut:ENable", True, self.c_inp_enq),
            ("INPut:LEVel:AMPlitude:CH", False, self.c_inp_lev),
            ("INPut:LEVel:AMPlitude:CH", True, self.c_inp_levq),
            ("OUTPut:ENable", False, self.c_out_en), ("OUTPut:ENable", True, self.c_out_enq),
            ("OUTPut:GAIN:CH", False, self.c_out_gain), ("OUTPut:GAIN:CH", True, self.c_out_gainq),
        ]
        return t

    def find(self, segments, is_query):
        for canonical, query, func in self.table():
            parts = canonical.split(":")
            if query == is_query and len(parts) == len(segments) and all(
                seg in forms(part) for seg, part in zip(segments, parts)
            ):
                return func
        return None

    def run_one(self, text):
        """Run a single command; returns a reply string or None."""
        word, _, rest = text.partition(" ")
        is_query = word.endswith("?")
        segments = word.rstrip("?").lstrip(":").lower().split(":")
        func = self.find(segments, is_query)
        if func is None:
            self.push_error(ERR_CMD)
            return None
        args = [x for x in rest.split(",")] if rest.strip() else []
        try:
            return func(args)
        except (ExecError, ValueError):
            self.push_error(ERR_STATE)
            return None

    def process(self, line):
        """Run a line (possibly several ';'-separated commands); returns reply lines."""
        replies = []
        with self.lock:
            for part in line.split(";"):
                part = part.strip()
                if part:
                    reply = self.run_one(part)
                    if reply is not None:
                        replies.append(reply)
        return replies


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        who = f"{self.client_address[0]}:{self.client_address[1]}"
        print(f"[{who}] connected")
        for raw in self.rfile:
            line = raw.decode(errors="replace").strip()
            if not line:
                continue
            print(f"[{who}] > {line}")
            for reply in self.server.emu.process(line):
                print(f"[{who}] < {reply}")
                self.wfile.write((reply + "\n").encode())
            self.wfile.flush()
        print(f"[{who}] disconnected")


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    ap = argparse.ArgumentParser(description="Mock PROPSIM ATE server")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=3334)
    ap.add_argument("--slow", type=float, default=0.0, help="seconds that open/connect/close take")
    ap.add_argument("--known-file", action="append", help="only accept this emulation file (repeatable)")
    args = ap.parse_args()

    server = Server((args.host, args.port), Handler)
    server.emu = Emulator(args.slow, args.known_file)
    print(f"Mock PROPSIM listening on {args.host}:{args.port} (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()