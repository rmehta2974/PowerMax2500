import threading
import requests
import json
import base64
import time
import logging
import sys

# --- Configuration ---
UNISPHERE_IP = "your_unisphere_ip"
USERNAME = "your_username"
PASSWORD = "your_password"
SYMMETRIX_ID = "000123456789"
LOG_FILE = "api_requests_py27_limit_test.log"
MAX_THREADS = 5  # Set to 5 to test concurrent client/POST limit
REQUEST_TIMEOUT = 300 # Timeout in seconds for each request
TARGET_DIRECTOR_PREFIXES = ["OR-1C", "OR-2C", "OR-3C", "OR-4C"] # Prefixes to identify target directors
# PRE_EXISTING_SG_IDS removed
# --- End Configuration ---

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s %(threadName)s - %(message)s',
    handlers=[logging.FileHandler(LOG_FILE, mode='w'), logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)
# --- End Logging Setup ---

THREAD_RESULTS = [] # Global list to store results
thread_pool_semaphore = threading.Semaphore(MAX_THREADS) # To limit active threads more globally

def make_api_request(session, method, url, task_name, payload=None, is_critical_setup_call=False):
    """
    Makes a synchronous API request (POST or GET), times it, and logs details.
    Returns the response data on success, or None on failure.
    """
    with thread_pool_semaphore: # Acquire a slot from the semaphore
        logger.info("{}: Sending {} to {}".format(task_name, method, url))
        if payload and method == "POST":
            logger.debug("{}: Payload: {}".format(task_name, json.dumps(payload)))
        
        start_time = time.time()
        response_data, status_code_val, error_message = None, "Unknown", None
        response_text_for_logging = ""

        try:
            if method == "POST":
                response = session.post(url, json=payload, verify=False, timeout=REQUEST_TIMEOUT)
            else: # GET
                response = session.get(url, verify=False, timeout=REQUEST_TIMEOUT)
            
            response_text_for_logging = response.text
            status_code_val = response.status_code
            response.raise_for_status()
            response_data = response.json()
        except requests.exceptions.HTTPError as e:
            error_message = "HTTP Error: {} - {}".format(e.response.status_code, e.message)
            logger.error("{}: {} from {}. Response: {}".format(task_name, error_message, url, response_text_for_logging[:500]))
            status_code_val = e.response.status_code
        except requests.exceptions.RequestException as e:
            error_message = "RequestException: {} - {}".format(type(e).__name__, e.message)
            logger.error("{}: {} while calling {}".format(task_name, error_message, url))
            status_code_val = "RequestException"
        except ValueError as e: # JSONDecodeError
            error_message = "JSONDecodeError: {}. Response: {}".format(e, response_text_for_logging[:500])
            logger.error("{}: {} from {}".format(task_name, error_message, url))
            status_code_val = "JSONDecodeError"
        except Exception as e:
            error_message = "Unexpected Exception: {} - {}".format(type(e).__name__, e.message)
            logger.exception("{}: {} while calling {}".format(task_name, error_message, url)) # .exception logs stack trace
            status_code_val = "Exception"
        finally:
            duration = time.time() - start_time
            log_level = logging.INFO if error_message is None else logging.ERROR
            logger.log(log_level, "{}: Finished. Status: {}, Duration: {:.4f}s".format(task_name, status_code_val, duration))
            
            result = {"task_name": task_name, "type": method, "url": url, "status_code": status_code_val, "duration": duration}
            if payload and method == "POST": result["payload"] = payload
            if error_message: result["error"] = error_message
            else: result["data"] = response_data
            THREAD_RESULTS.append(result)

            if error_message and is_critical_setup_call:
                logger.critical("{}: Critical setup call failed. Subsequent steps might be affected.".format(task_name))
                return None # Indicate failure
            return response_data

def process_director_and_ports(session, base_url_v100, director_info):
    """
    Processes a single director: gets its ports, and then details for each port.
    """
    director_id = director_info.get("directorId")
    if not director_id:
        logger.warning("Skipping director due to missing 'directorId': {}".format(director_info))
        return

    logger.info("Processing Director ID: {}".format(director_id))
    
    ports_url = "{}/system/symmetrix/{}/director/{}/port".format(base_url_v100, SYMMETRIX_ID, director_id)
    ports_task_name = "GET_Ports_for_Dir_{}".format(director_id)
    ports_data = make_api_request(session, "GET", ports_url, ports_task_name)

    if ports_data and ports_data.get("symmetrixPortKey"):
        port_threads = []
        for port_key_info in ports_data.get("symmetrixPortKey", []):
            port_id = port_key_info.get("portId")
            if port_id is not None:
                port_detail_url = "{}/system/symmetrix/{}/director/{}/port/{}".format(base_url_v100, SYMMETRIX_ID, director_id, port_id)
                port_detail_task_name = "GET_PortDetail_Dir_{}_Port_{}".format(director_id, port_id)
                thread = threading.Thread(target=make_api_request, args=(session, "GET", port_detail_url, port_detail_task_name))
                port_threads.append(thread)
                thread.start()
            else:
                logger.warning("Skipping port in director {} due to missing 'portId': {}".format(director_id, port_key_info))
        
        for t in port_threads:
            t.join()
    elif ports_data and not ports_data.get("symmetrixPortKey"):
        logger.info("No ports found or 'symmetrixPortKey' missing for director {}".format(director_id))
    else:
        logger.error("Failed to get ports for director {}".format(director_id))


def main():
    logger.info("Script starting API Limit Test. Target: {}, Array: {}, Max Threads: {}".format(UNISPHERE_IP, SYMMETRIX_ID, MAX_THREADS))
    # Removed PRE_EXISTING_SG_IDS check as it's no longer used for specific GETs

    try:
        requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)
    except AttributeError: pass

    base_url_v102 = "https://{}:8443/univmax/restapi/102".format(UNISPHERE_IP)
    auth_header = "Basic {}".format(base64.b64encode("{}:{}".format(USERNAME, PASSWORD)).decode('utf-8'))
    session_headers = {"Content-Type": "application/json", "Accept": "application/json", "Authorization": auth_header}

    with requests.Session() as session:
        session.headers.update(session_headers)
        
        # --- Stage 1: Get Director Info and Process Target Directors ---
        logger.info("--- Stage 1: Fetching and Processing Target Director Ports ---")
        directors_url = "{}/system/symmetrix/{}/director".format(base_url_v100, SYMMETRIX_ID)
        directors_data = make_api_request(session, "GET", directors_url, "GET_All_Directors", is_critical_setup_call=True)
        
        target_director_threads = []
        if directors_data:
            found_director_infos = []
            director_list_key = None
            # Attempt to find the list of director objects in the response
            if "symmetrixDirector" in directors_data: director_list_key = "symmetrixDirector"
            elif "director" in directors_data and isinstance(directors_data["director"], list): director_list_key = "director"
            elif "director_info" in directors_data and isinstance(directors_data["director_info"], list): director_list_key = "director_info"
            elif "directorId" in directors_data and isinstance(directors_data["directorId"], list) and len(directors_data) == 1: # Less likely for rich info
                for did in directors_data["directorId"]: found_director_infos.append({"directorId": did}) # Create mock objects
            
            if director_list_key: found_director_infos = directors_data.get(director_list_key, [])


            for director_obj in found_director_infos:
                current_director_id = director_obj.get("directorId")
                if current_director_id:
                    for prefix in TARGET_DIRECTOR_PREFIXES:
                        if current_director_id.startswith(prefix):
                            logger.info("Found target director: {}. Queuing for port processing.".format(current_director_id))
                            thread = threading.Thread(target=process_director_and_ports, args=(session, base_url_v100, director_obj))
                            target_director_threads.append(thread)
                            thread.start()
                            break 
        else:
            logger.error("Could not retrieve director list. Skipping director/port specific calls.")

        for t in target_director_threads: t.join()
        logger.info("--- Stage 1: Finished Target Director and Port Processing ---")

        # --- Stage 2: Standard POST and GET Requests ---
        logger.info("--- Stage 2: Starting Standard POST and GET API Calls ---")
        standard_threads = []
        post_endpoint = "{}/sloprovisioning/symmetrix/{}/storagegroup".format(base_url_v100, SYMMETRIX_ID)
        for i in range(5): 
            sg_id = "MyPy27LimitTestSG_New_{}".format(i + 1)
            payload = {"executionOption": "SYNCHRONOUS", "storageGroupId": sg_id, "srpId": "YOUR_ACTUAL_SRP_ID", 
                       "sloBasedStorageGroupParam": [{"sloId": "Diamond", "volumeAttributes": [{"volume_size": "10", "size_unit": "GB", "num_of_vols": "1"}]}],
                       "emulation": "FBA"}
            task_name = "POST_SG_{}".format(sg_id)
            standard_threads.append(threading.Thread(target=make_api_request, args=(session, "POST", post_endpoint, task_name, payload)))

        # --- GET Requests Definitions (Aiming for 50 predefined GETs) ---
        # 1 SRP call + 7 other categories. 50 - 1 = 49 calls for other categories.
        # 49 calls / 7 categories = 7 calls per category.
        calls_per_category = 7
        
        other_get_defs = [
            ("{}/sloprovisioning/symmetrix/{}/storagegroup", "GET_SG_List", calls_per_category),
            ("{}/system/symmetrix/{}/health", "GET_Sys_Health", calls_per_category),
            ("{}/sloprovisioning/symmetrix/{}/volume", "GET_Volume_List", calls_per_category),
            ("{}/sloprovisioning/symmetrix/{}/portgroup", "GET_PortGroup_List", calls_per_category),
            ("{}/sloprovisioning/symmetrix/{}/maskingview", "GET_MaskingView_List", calls_per_category),
            ("{}/sloprovisioning/symmetrix/{}/srp", "GET_SRP_List", 1), # Always 1 SRP call
            ("{}/performance/Array/{}/category", "GET_Perf_ArrayCat", calls_per_category),
            ("{}/performance/FEDirector/keys?symmetrixId={}", "GET_Perf_FEDirKeys", calls_per_category)
        ]
        
        for url_template, name_prefix, count_for_def in other_get_defs:
            for i in range(int(count_for_def)): # Ensure count is int
                task_name = "{}_{}".format(name_prefix, i + 1)
                # Most URLs just need base_url and SYMMETRIX_ID
                url = url_template.format(base_url_v100, SYMMETRIX_ID)
                # Special handling for FEDirector/keys as SYMMETRIX_ID is already in its template
                if name_prefix == "GET_Perf_FEDirKeys":
                    url = url_template.format(base_url_v100, SYMMETRIX_ID) # Already correct

                standard_threads.append(threading.Thread(target=make_api_request, args=(session, "GET", url, task_name)))
        
        for t in standard_threads: t.start()
        for t in standard_threads: t.join()
        logger.info("--- Stage 2: Finished Standard POST and GET API Calls ---")

        logger.info("\n--- API Call Results Summary (All Stages) ---")
        summary = {"POST": {"total":0, "ok":0, "err":0, "duration":0.0}, "GET": {"total":0, "ok":0, "err":0, "duration":0.0}}
        for r in THREAD_RESULTS:
            cat = r["type"]
            if cat not in summary: summary[cat] = {"total":0, "ok":0, "err":0, "duration":0.0} # Should not happen
            summary[cat]["total"] += 1
            summary[cat]["duration"] += r["duration"]
            if "error" not in r and isinstance(r["status_code"], int) and r["status_code"] < 400:
                summary[cat]["ok"] += 1
            else:
                summary[cat]["err"] += 1
        
        for method_type, data in summary.items():
            if data["total"] > 0:
                avg_dur = data["duration"] / data["total"]
                logger.info("{}s: Total={}, OK={}, Err={}, AvgDur={:.4f}s".format(method_type, data["total"], data["ok"], data["err"], avg_dur))
            else:
                logger.info("{}s: No tasks processed.".format(method_type))

    logger.info("Script finished. Log: {}".format(LOG_FILE))

if __name__ == "__main__":
    del THREAD_RESULTS[:]
    try:
        main()
    except KeyboardInterrupt: logger.info("Script cancelled by user.")
    except Exception as e: logger.critical("Unhandled error: {}".format(e), exc_info=True)
