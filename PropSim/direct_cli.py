'''
This python script acts as a direct command line interface to the PropSim hardware. 
It allows the user to run emulations on the PropSim hardware without using the GUI
and is useful for testing ATE commands on the PropSim.
'''

from Propsim import *



def print_propsim_response(response):
    print("Propsim: " + response)

def print_client_command(command):
    print("Client: " + command)

def main():
    ps = Propsim(host="127.0.0.1")

    while True:
        command = input("Client: ").strip()
        if not command: #if the user just presses enter, continue to the next iteration of the loop
            continue
        if command.lower() in ("quit", "exit"):
            break
        
        if command.split()[0].endswith("?"):   # first word ends in ? -> it's a query
            response = ps.query(command)
            print_propsim_response(response)
        else:
            ps.write(command)

    ps.write('*RST') #reset the Propsim to its default state before exiting

if __name__ == "__main__":
    main()