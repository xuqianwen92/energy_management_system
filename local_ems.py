# The main entrance of local energy management system (UEMS)
# Date: 4/Sep/2017
# Authors: Tianyang Zhao
# Mail: zhaoty@ntu.edu.sg
from apscheduler.schedulers.blocking import BlockingScheduler  # Time scheduler

import configuration.configuration_database as db_configuration  # The settings of databases
from sqlalchemy import create_engine  # Import database
from sqlalchemy.orm import sessionmaker
import zmq  # The package for information and communication

import modelling.information_exchange_pb2 as opf_model  # The information model of optimal power flow
import modelling.dynamic_operation_pb2 as economic_dispatch_info  # The information model of economic dispatch

from modelling import generators, loads, energy_storage_systems, convertors
from data_management.information_management import information_receive_send

from start_up import static_information

from optimal_power_flow.main import short_term_operation
from economic_dispatch.main import middle_term_operation
from unit_commitment.main import long_term_operation

from utils import Logger

logger = Logger("Local_ems")

def run():
    # Define the local models
    local_models = {"DG": generators.Generator_AC.copy(),
                    "UG": generators.Generator_AC.copy(),
                    "Load_ac": loads.Load_AC.copy(),
                    "Load_uac": loads.Load_AC.copy(),
                    "BIC": convertors.BIC.copy(),
                    "ESS": energy_storage_systems.BESS.copy(),
                    "PV": generators.Generator_RES.copy(),
                    "WP": generators.Generator_RES.copy(),
                    "Load_dc": loads.Load_DC.copy(),
                    "Load_udc": loads.Load_DC.copy(),
                    "PMG": 0,
                    "VDC": 0}

    # Update the local parameters
    local_models["UG"]["GEN_STATUS"] = 0
    local_models["WP"]["GEN_STATUS"] = 0
    local_models["Load_ac"]["FLEX"] = 0
    local_models["Load_uac"]["FLEX"] = 1
    local_models["Load_dc"]["FLEX"] = 0
    local_models["Load_udc"]["FLEX"] = 1
    # Convert local information to sharable information
    static_info = static_information.static_information_generation(local_models)
    # Set the database information
    db_str = db_configuration.local_database["db_str"]
    engine = create_engine(db_str, echo=False)
    Session = sessionmaker(bind=engine)
    session_lems = Session()

    # Start the information connection
    context = zmq.Context()
    socket = context.socket(zmq.REQ)
    socket.connect("tcp://localhost:5555")

    socket_upload = context.socket(zmq.REQ)
    socket_upload.connect("tcp://localhost:5556")

    socket_download = context.socket(zmq.REP)
    socket_download.connect("tcp://localhost:5557")

    while True:
        socket.send(b"ConnectionRequest")

        message = socket.recv()
        if message == b"Start!":
            logger.info("The connection between the local EMS and universal EMS establishes!")
            break
        else:
            logger.error("Waiting for the connection between the local EMS and universal EMS!")

    information_receive_send.information_send(socket, static_info, 2)

    info_ed = economic_dispatch_info.local_sources()
    info_uc = economic_dispatch_info.local_sources() # The information model in the
    info_opf = opf_model.informaiton_exchange()  # The optimal power flow modelling
    # By short-term operation process
    logger.info("The short-term process in local ems starts!")
    sched_short_term = BlockingScheduler()  # The schedulor for the optimal power flow
    sched_short_term.add_job(
        lambda: short_term_operation.short_term_operation_lems(local_models, socket_upload, socket_download, info_opf,
                                                               session_lems),
        'cron', minute='0-59', second='1')  # The operation is triggered minutely
    sched_short_term.start()


    short_term_operation.short_term_operation_lems(local_models, socket_upload, socket_download, info_opf,
                                                   session_lems)
    logger.info("The middle-term process in local EMS starts!")
    sched_middle_term = BlockingScheduler()  # The schedulor for the optimal power flow
    sched_middle_term.add_job(
        lambda: middle_term_operation.middle_term_operation_lems(local_models, socket_upload, socket_download, info_ed,
                                                                 session_lems),
        'cron', minute='*/5', second='1')  # The operation is triggered every five minute
    sched_middle_term.start()


    logger.info("The long term process in local EMS starts!")
    sched_long_term = BlockingScheduler()  # The schedulor for the optimal power flow
    sched_long_term.add_job(
        lambda: long_term_operation.long_term_operation_lems(local_models, socket_upload, socket_download, info_uc,
                                                                 session_lems),
        'cron', minute='*/30', second='1')  # The operation is triggered every half an hour
    sched_long_term.start()

if __name__ == "__main__":
    ## Start the main process of local energy management system
    run()