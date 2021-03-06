# Main entrance for the short-term operation of both universal ems and local ems
import threading
import time
from configuration.configuration_time_line import default_time
from data_management.information_collection import Information_Collection_Thread
from data_management.information_management import information_formulation_extraction
from data_management.information_management import information_receive_send
from optimal_power_flow.short_term_forecasting import ForecastingThread
from configuration.configuration_time_line import default_dead_line_time
from utils import Logger
from configuration.configuration_time_line import default_look_ahead_time_step
logger_uems = Logger("Short_term_dispatch_UEMS")
logger_lems = Logger("Short_term_dispatch_LEMS")

class short_term_operation():
    ##short term operation for ems
    # Two modes are proposed for the local ems and
    def short_term_operation_uems(*args):

        from data_management.database_management import database_operation
        from optimal_power_flow.problem_formulation import problem_formulation
        from optimal_power_flow.problem_solving import Solving_Thread
        # Short term operation
        # General procedure for short-term operation
        # 1)Information collection
        # 1.1)local EMS forecasting
        # 1.2)Information exchange
        universal_models = args[0]
        local_models = args[1]
        socket_upload = args[2]
        socket_download = args[3]
        info = args[4]
        session = args[5]

        Target_time = time.time()
        Target_time = round((Target_time - Target_time % default_time["Time_step_opf"] + default_time[
            "Time_step_opf"]))

        # Update the universal parameter by using the database engine
        # Two threads are created to obtain the information simultaneously.
        thread_forecasting = ForecastingThread(session, Target_time, universal_models)
        thread_info_ex = Information_Collection_Thread(socket_upload, info, local_models,default_look_ahead_time_step["Look_ahead_time_opf_time_step"])

        thread_forecasting.start()
        thread_info_ex.start()

        thread_forecasting.join()
        thread_info_ex.join()

        universal_models = thread_forecasting.models
        local_models = thread_info_ex.local_models
        # Solve the optimal power flow problem
        # Two threads will be created, one for feasible problem, the other for infeasible problem
        mathematical_model = problem_formulation.problem_formulation_universal(local_models, universal_models,
                                                                              "Feasible")
        mathematical_model_recovery = problem_formulation.problem_formulation_universal(local_models, universal_models,
                                                                                       "Infeasible")
        # Solve the problem
        res = Solving_Thread(mathematical_model)
        res_recovery = Solving_Thread(mathematical_model_recovery)
        res.daemon = True
        res_recovery.daemon = True

        res.start()
        res_recovery.start()

        res.join(default_dead_line_time["Gate_closure_opf"])
        res_recovery.join(default_dead_line_time["Gate_closure_opf"])

        if res.value["success"] == True:
            (local_models, universal_models) = result_update(res.value, local_models, universal_models, "Feasible")
        else:
            (local_models, universal_models) = result_update(res_recovery.value, local_models, universal_models,
                                                             "Infeasible")

        # Return command to the local ems
        dynamic_model = information_formulation_extraction.info_formulation(local_models, Target_time)
        dynamic_model.TIME_STAMP_COMMAND = round(time.time())

        information_send_thread = threading.Thread(target=information_receive_send.information_send,
                                                   args=(socket_upload, dynamic_model, 2))

        database_operation__uems = threading.Thread(target=database_operation.database_record,
                                                    args=(session, universal_models, Target_time, "OPF"))
        logger_uems.info("The command for UEMS is {}".format(universal_models["PMG"]))
        information_send_thread.start()
        database_operation__uems.start()

        information_send_thread.join()
        database_operation__uems.join()

    def short_term_operation_lems(*args):
        from data_management.database_management import database_operation
        # Short term operation for local ems
        # The following operation sequence
        # 1) Information collection
        # 2) Short-term forecasting
        # 3) Information upload and database store
        # 4) Download command and database operation
        local_models = args[0]  # Local energy management system models
        socket_upload = args[1]  # Upload information channel
        socket_download = args[2]  # Download information channel
        info = args[3]  # Information structure
        session = args[4]  # local database

        Target_time = time.time()
        Target_time = round((Target_time - Target_time % default_time["Time_step_opf"] + default_time[
            "Time_step_opf"]))

        # Step 1: Short-term forecasting
        thread_forecasting = ForecastingThread(session, Target_time, local_models)  # The forecasting thread
        thread_forecasting.start()
        thread_forecasting.join()

        local_models = thread_forecasting.models
        # Update the dynamic model
        dynamic_model = information_formulation_extraction.info_formulation(local_models, Target_time)
        # Information send
        logger_lems.info("Sending request from {}".format(dynamic_model.AREA) + " to the serve")
        logger_lems.info("The local time is {}".format(dynamic_model.TIME_STAMP))
        information_receive_send.information_send(socket_upload, dynamic_model, 2)

        # Step2: Backup operation, which indicates the universal ems is down

        # Receive information from uems
        dynamic_model = information_receive_send.information_receive(socket_upload, info, 2)
        # print("The universal time is", dynamic_model.TIME_STAMP_COMMAND)
        logger_lems.info("The command from UEMS is {}".format(dynamic_model.PMG))
        # Store the data into the database

        local_models = information_formulation_extraction.info_extraction(local_models, dynamic_model)

        database_operation.database_record(session, local_models, Target_time, "OPF")


def result_update(*args):
    ## Result update for local ems and universal ems models
    res = args[0]
    local_model = args[1]
    universal_model = args[2]
    type = args[3]

    if type == "Feasible":
        from modelling.power_flow.idx_format import NX
    else:
        from modelling.power_flow.idx_format_recovery import NX

    x_local = res["x"][0:NX]
    x_universal = res["x"][NX:2 * NX]

    local_model = update(x_local, local_model, type)
    universal_model = update(x_universal, universal_model, type)

    return local_model, universal_model


def update(*args):
    x = args[0]
    model = args[1]
    model_type = args[2]

    if model_type == "Feasible":
        from modelling.power_flow.idx_format import PG, QG, RG, PUG, QUG, RUG, PBIC_AC2DC, PBIC_DC2AC, QBIC, PESS_C, \
            PESS_DC, RESS, PMG

        model["DG"]["COMMAND_PG"] = int(x[PG])
        model["DG"]["COMMAND_QG"] = int(x[QG])
        model["DG"]["COMMAND_RG"] = int(x[RG])

        model["UG"]["COMMAND_PG"] = int(x[PUG])
        model["UG"]["COMMAND_QG"] = int(x[QUG])
        model["UG"]["COMMAND_RG"] = int(x[RUG])

        model["BIC"]["COMMAND_AC2DC"] = int(x[PBIC_AC2DC])
        model["BIC"]["COMMAND_DC2AC"] = int(x[PBIC_DC2AC])

        model["BIC"]["COMMAND_Q"] = int(x[QBIC])

        model["ESS"]["COMMAND_PG"] = int(x[PESS_DC]) - int(x[PESS_C])
        model["ESS"]["COMMAND_RG"] = int(x[RESS])

        model["PMG"] = int(x[PMG])
    else:
        from modelling.power_flow.idx_format_recovery import PG, QG, RG, PUG, QUG, RUG, PBIC_AC2DC, PBIC_DC2AC, QBIC, \
            PESS_C, PESS_DC, RESS, PMG, PPV, PWP, PL_AC, PL_UAC, PL_DC, PL_UDC
        model["DG"]["COMMAND_PG"] = int(x[PG])
        model["DG"]["COMMAND_QG"] = int(x[QG])
        model["DG"]["COMMAND_RG"] = int(x[RG])

        model["UG"]["COMMAND_PG"] = int(x[PUG])
        model["UG"]["COMMAND_QG"] = int(x[QUG])
        model["UG"]["COMMAND_RG"] = int(x[RUG])

        model["BIC"]["COMMAND_AC2DC"] = int(x[PBIC_AC2DC])
        model["BIC"]["COMMAND_DC2AC"] = int(x[PBIC_DC2AC])
        model["BIC"]["COMMAND_Q"] = int(x[QBIC])

        model["ESS"]["COMMAND_PG"] = int(x[PESS_DC]) - int(x[PESS_C])
        model["ESS"]["COMMAND_RG"] = int(x[RESS])

        model["PMG"] = int(x[PMG])
        
        if type(model["PV"]["PG"]) is list:
            model["PV"]["COMMAND_CURT"] = int(model["PV"]["PG"][0]) - int(x[PPV])
        else:
            model["PV"]["COMMAND_CURT"] = int(model["PV"]["PG"]) - int(x[PPV])

        if type(model["WP"]["PG"]) is list:
            model["WP"]["COMMAND_CURT"] = int(model["WP"]["PG"][0]) - int(x[PWP])
        else:
            model["WP"]["COMMAND_CURT"] = int(model["WP"]["PG"]) - int(x[PWP])

        if type(model["Load_ac"]["PD"]) is list:
            model["Load_ac"]["COMMAND_SHED"] = int(model["Load_ac"]["PD"][0]) - int(x[PL_AC])
        else:
            model["Load_ac"]["COMMAND_SHED"] = int(model["Load_ac"]["PD"]) - int(x[PL_AC])

        if type(model["Load_uac"]["PD"]) is list:
            model["Load_uac"]["COMMAND_SHED"] = int(model["Load_uac"]["PD"][0]) - int(x[PL_UAC])
        else:
            model["Load_uac"]["COMMAND_SHED"] = int(model["Load_uac"]["PD"]) - int(x[PL_UAC])

        if type(model["Load_dc"]["PD"]) is list:
            model["Load_dc"]["COMMAND_SHED"] = int(model["Load_dc"]["PD"][0]) - int(x[PL_DC])
        else:
            model["Load_dc"]["COMMAND_SHED"] = int(model["Load_dc"]["PD"]) - int(x[PL_DC])
        
        if type(model["Load_dc"]["PD"]) is list:
            model["Load_udc"]["COMMAND_SHED"] = int(model["Load_udc"]["PD"][0]) - int(x[PL_UDC])
        else:
            model["Load_udc"]["COMMAND_SHED"] = int(model["Load_udc"]["PD"]) - int(x[PL_UDC])

    return model
