import socket
default_ip = "X.X.X.PLACEHOLDER"

class Propsim:
    def __init__(self, host=default_ip, port=3334, timeout=10):
        self.timeout = timeout
        self.sock = socket.create_connection((host, port), timeout)
        self.stream = self.sock.makefile("rw", newline="\n")

    def disconnect(self):
        self.stream.close()
        self.sock.close()

    #sends command to Propsim, does not wait for a reply
    def write(self, cmd):
        self.stream.write(cmd + "\n")
        self.stream.flush()

    #use when sending a command and you expect a reply back
    def query(self, cmd):
        self.write(cmd)
        return self.stream.readline().strip()

    #Block until pending operations finish (*OPC?), using a longer timeout.
    def wait(self, timeout=120): #Use timeout=None if you want to wait indefinitely
        self.sock.settimeout(timeout)
        try:
            self.query("*OPC?") #returns "1" when after no more pending operations
        finally:
            self.sock.settimeout(self.timeout) #reset to original timeout

    #Drain the error queue; returns a list of error strings (empty if none).
    def errors(self):
        out = []
        while True:
            e = self.query("SYSTem:ERRor?") #get first error from queue, or "0,No error" if none
            if e.startswith("0,"):
                return out
            out.append(e)

    #open an existing emulation and load it to hardware
    def open(self, path):
        self.clear_status()  #clear status and error queue
        self.write(f"CALCulate:FILTer:FILE {path}")
        self.wait()
        err = self.errors()
        if err:
            raise RuntimeError(err)

    #opens emulation defined in file <filename> to editing mode,
    #allowing user to change emulation settings before loading emulation to hardware
    #this is useful if you want to edit an emulation while another emulation is running on the hardware
    def edit(self, path):
        self.clear_status()  #clear status and error queue
        self.write(f"CALCulate:FILTer:EDIT {path}")
        self.wait()
        err = self.errors()
        if err:
            raise RuntimeError(err)

    #loads to hardware the emulation opened with CALCulate:FILTer:EDIT
    def connect(self):
        self.write("CALCulate:FILTer:CONNECT")

    def clear_status(self):
        self.write("*CLS")

    #run emulation
    def run(self):
        self.write("DIAGnostic:SIMUlation:GO")

    #pause emulation
    def stop(self):
        self.write("DIAGnostic:SIMUlation:STOP")

    #pause emulation and rewind to beginning
    def rewind(self):
        self.write("DIAGnostic:SIMUlation:GOStart")
    
    #continue paused emulation
    def continue_(self):
        self.write("DIAGnostic:SIMUlation:CONTinue")

    #returns running state of the emulation
    def state(self):
        return self.query("DIAGnostic:SIMUlation:STATE?")

    #closes open emulation
    def close(self):
        self.write("DIAGnostic:SIMUlation:CLOSE")




    '''
    Commands that edit emulation parameters, only use after an emulation has been opened in EDIT mode
    '''

    #This command sets the average input level of the specific channel input in dBm. 
    def set_input_level(self, ch, dbm):
        self.write(f"INPut:LEVel:AMPlitude:CH {ch},{dbm}")

    #This command sets the gain of the specific channel output in dB. 
    def set_output_gain(self, ch, db):
        self.write(f"OUTPut:GAIN:CH {ch},{db}")