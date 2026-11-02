# lunar-5G-MQP
Emulating 5G on the moon with Keysight PropSim

"This project develops a proof-of-concept hardware emulation platform for evaluating 5G wireless communications on the lunar surface. The work focuses on implementing theoretical lunar wireless channel models on a Keysight PROPSIM digital channel emulator to recreate realistic lunar propagation conditions. Using a combination of open-source 5G technologies, including srsRAN, EMANE, and Open5GS, the project will construct and evaluate a functional 5G network capable of supporting multiple user devices, potentially up to 16 simultaneous users. The system will incorporate multiple software-defined radio (SDR) technologies, including the USRP X310 and LimeSDR Mini, while also involving RF engineering concepts such as antenna integration, signal chain design, and radio-frequency performance evaluation. The resulting testbed will enable experimentation with network performance, propagation effects, SDR-based communications, and multi-user communication behavior in a simulated lunar environment, providing a foundation for future extraterrestrial wireless networking research and development."


This repository contains a GUI application which improves the workflow of OAI's RF Simulator. The GUI's advantage is placing and visualizing gNB and UE locations, as well as allowing the user to change DEM files/simulated environments easily. Future work includes making this tool more versitile and robust, expanding the library to include more environments and shaping it as a general open-source tool for lunar and terrestrial environments.

To run the GUI, start in the files directory and run:

python ./lunar_site_planner.py

For the GUI to run, it needs a .bdem and .tif file for each site. lunar_site_planner pulls from atlas_v2 and terrain folders to visualize the candidate landing sites. This is the rough file structure:

- files
    - atlas_v2: 
    - data:
    - exports: 
    - templates:
    - terrain:
- scripts
    - 

