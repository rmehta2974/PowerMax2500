import asyncio
import aiohttp
import json
import base64
import time # For timing API calls
import logging # For logging
import sys # For checking platform if needed for asyncio policy

# --- Configuration - Replace with your actual values ---
UNISPHERE_IP = "your_unisphere_ip"  # Replace with your Unisphere for PowerMax IP address
USERNAME = "your_username"          # Replace with your username
PASSWORD = "your_password"          # Replace with your password
SYMMETRIX_ID = "000123456789"       # Replace with your PowerMax Array Symmetrix ID
LOG_FILE = "api_requests.log"       # Name of the log file
# --- End Configuration ---

# --- Logging Setup ---
# Configure logging to write to a file and to the console
logging.basicConfig(
    level=logging.INFO, # Set to logging.DEBUG for more verbose output (e.g., full payloads)
    format='%(asctime)s - %(levelname)s - %(name)s - %(filename)s:%(lineno)d - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, mode='w'), # 'w' to overwrite log file on each run, 'a' to append
        logging.StreamHandler(sys.stdout)      # Log to console
    ]
)
logger = logging.getLogger(__name__) # Get a logger instance for this module
# --- End Logging Setup ---

BASE_URL = f"https://{UNISPHERE_IP}:8443/univmax/restapi/100" # Using API version 100

# Create Basic Auth header
# This is done once and reused for all requests
auth_string = f"{USERNAME}:{PASSWORD}"
auth_header_value = base64.b64encode(auth_string.encode('utf-8')).decode('utf-8')
# HEADERS dictionary is defined here but will be passed to ClientSession constructor
SESSION_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Authorization": f"Basic {auth_header_value}"
}

# --- Helper Functions with Timing and Logging ---
async def make_post_request(session, url, payload, task_name="POST Task"):
    """
    Makes an asynchronous POST request, times it, and logs details.
    Headers are taken from the session.
    """
    logger.info(f"{task_name}: Sending POST to {url}")
    logger.debug(f"{task_name}: Payload: {json.dumps(payload)}")
    start_time = time.perf_counter()
    response_data = None
    status_code_val = "Unknown"
    error_message = None
    response_text_for_logging = "" # Initialize to avoid reference before assignment in finally if early exception

    try:
        async with session.post(url, json=payload, ssl=False) as response:
            response_text_for_logging = await response.text()
            status_code_val = response.status
            response.raise_for_status()
            response_data = await response.json()
    except aiohttp.ClientResponseError as e:
        error_message = f"HTTP Error: {e.status} - {e.message}"
        # response_text_for_logging would have been set if response was received before error
        logger.error(f"{task_name}: {error_message} from {url}. Response headers: {e.headers}. Response body snippet: {response_text_for_logging[:500]}...")
        status_code_val = e.status
    except aiohttp.ClientError as e:
        error_message = f"ClientError: {type(e).__name__} - {e}"
        logger.error(f"{task_name}: {error_message} while calling {url}")
        status_code_val = "ClientError"
    except json.JSONDecodeError as e:
        error_message = f"JSONDecodeError: Failed to decode JSON response - {e}. Response text: {response_text_for_logging[:500]}"
        logger.error(f"{task_name}: {error_message} from {url}")
        status_code_val = "JSONDecodeError"
    except Exception as e:
        error_message = f"Unexpected Exception: {type(e).__name__} - {e}"
        logger.exception(f"{task_name}: {error_message} while calling {url}")
        status_code_val = "Exception"
    finally:
        duration = time.perf_counter() - start_time
        log_level = logging.INFO if error_message is None else logging.ERROR
        logger.log(log_level, f"{task_name}: Finished. Status: {status_code_val}, Duration: {duration:.4f}s, URL: {url}")
        if error_message:
             return {"error": error_message, "status_code": status_code_val, "duration": duration, "url": url, "payload": payload}
        return {"data": response_data, "status_code": status_code_val, "duration": duration}


async def make_get_request(session, url, task_name="GET Task"):
    """
    Makes an asynchronous GET request, times it, and logs details.
    Headers are taken from the session.
    """
    logger.info(f"{task_name}: Sending GET to {url}")
    start_time = time.perf_counter()
    response_data = None
    status_code_val = "Unknown"
    error_message = None
    response_text_for_logging = ""

    try:
        async with session.get(url, ssl=False) as response:
            response_text_for_logging = await response.text()
            status_code_val = response.status
            response.raise_for_status()
            response_data = await response.json()
    except aiohttp.ClientResponseError as e:
        error_message = f"HTTP Error: {e.status} - {e.message}"
        logger.error(f"{task_name}: {error_message} from {url}. Response headers: {e.headers}. Response body snippet: {response_text_for_logging[:500]}...")
        status_code_val = e.status
    except aiohttp.ClientError as e:
        error_message = f"ClientError: {type(e).__name__} - {e}"
        logger.error(f"{task_name}: {error_message} while calling {url}")
        status_code_val = "ClientError"
    except json.JSONDecodeError as e:
        error_message = f"JSONDecodeError: Failed to decode JSON response - {e}. Response text: {response_text_for_logging[:500]}"
        logger.error(f"{task_name}: {error_message} from {url}")
        status_code_val = "JSONDecodeError"
    except Exception as e:
        error_message = f"Unexpected Exception: {type(e).__name__} - {e}"
        logger.exception(f"{task_name}: {error_message} while calling {url}")
        status_code_val = "Exception"
    finally:
        duration = time.perf_counter() - start_time
        log_level = logging.INFO if error_message is None else logging.ERROR
        logger.log(log_level, f"{task_name}: Finished. Status: {status_code_val}, Duration: {duration:.4f}s, URL: {url}")
        if error_message:
            return {"error": error_message, "status_code": status_code_val, "duration": duration, "url": url}
        return {"data": response_data, "status_code": status_code_val, "duration": duration}


async def main():
    """
    Main function to prepare and run concurrent API tasks.
    """
    logger.info(f"Script starting. Target Unisphere: {UNISPHERE_IP}, Array ID: {SYMMETRIX_ID}")
    logger.info(f"Logging to file: {LOG_FILE}")

    timeout = aiohttp.ClientTimeout(total=300) # 5 minutes total timeout for a request

    async with aiohttp.ClientSession(headers=SESSION_HEADERS, timeout=timeout) as session:
        post_tasks = []
        get_tasks = []

        # --- Define POST Requests (Example: Create Storage Groups) ---
        post_endpoint = f"{BASE_URL}/sloprovisioning/symmetrix/{SYMMETRIX_ID}/storagegroup"
        logger.info(f"Preparing 5 POST requests to endpoint: {post_endpoint}")
        for i in range(5):
            storage_group_id = f"MyAsyncSG_Ext_{i+1}"
            payload = {
                "executionOption": "SYNCHRONOUS",
                "storageGroupId": storage_group_id,
                "srpId": "SRP_1",
                "sloBasedStorageGroupParam": [{"sloId": "Diamond", "volumeAttributes": [{"volume_size": "10", "size_unit": "GB", "num_of_vols": "1"}]}],
                "emulation": "FBA"
            }
            post_tasks.append(make_post_request(session, post_endpoint, payload, task_name=f"POST Task-{i+1} (Create SG {storage_group_id})"))

        # --- Define GET Requests (50 total) ---
        logger.info(f"Preparing 50 diverse GET requests.")
        
        # Category 1: Storage Group Specific (5 calls)
        for i in range(5):
            sg_to_get = f"MyAsyncSG_Ext_{(i % 5) + 1}" # Assumes POSTs might create these
            url = f"{BASE_URL}/sloprovisioning/symmetrix/{SYMMETRIX_ID}/storagegroup/{sg_to_get}"
            get_tasks.append(make_get_request(session, url, task_name=f"GET Task SG Specific-{i+1} (Get SG {sg_to_get})"))

        # Category 2: Storage Group List All (5 calls)
        url_sg_list = f"{BASE_URL}/sloprovisioning/symmetrix/{SYMMETRIX_ID}/storagegroup"
        for i in range(5):
            get_tasks.append(make_get_request(session, url_sg_list, task_name=f"GET Task SG List-{i+1}"))

        # Category 3: System Health (5 calls)
        url_health = f"{BASE_URL}/system/symmetrix/{SYMMETRIX_ID}/health"
        for i in range(5):
            get_tasks.append(make_get_request(session, url_health, task_name=f"GET Task System Health-{i+1}"))

        # Category 4: Directors List All (5 calls)
        url_directors = f"{BASE_URL}/system/symmetrix/{SYMMETRIX_ID}/director"
        for i in range(5):
            get_tasks.append(make_get_request(session, url_directors, task_name=f"GET Task Directors List-{i+1}"))
            
        # Category 5: Volumes List All on Array (5 calls)
        url_volumes_all = f"{BASE_URL}/sloprovisioning/symmetrix/{SYMMETRIX_ID}/volume"
        for i in range(5):
            get_tasks.append(make_get_request(session, url_volumes_all, task_name=f"GET Task Volumes All-{i+1}"))

        # Category 6: Port Groups List All (5 calls)
        url_portgroups = f"{BASE_URL}/sloprovisioning/symmetrix/{SYMMETRIX_ID}/portgroup"
        for i in range(5):
            get_tasks.append(make_get_request(session, url_portgroups, task_name=f"GET Task PortGroups List-{i+1}"))

        # Category 7: Masking Views List All (5 calls)
        url_maskingviews = f"{BASE_URL}/sloprovisioning/symmetrix/{SYMMETRIX_ID}/maskingview"
        for i in range(5):
            get_tasks.append(make_get_request(session, url_maskingviews, task_name=f"GET Task MaskingViews List-{i+1}"))
            
        # Category 8: SRPs List All (5 calls)
        url_srps = f"{BASE_URL}/sloprovisioning/symmetrix/{SYMMETRIX_ID}/srp"
        for i in range(5):
            get_tasks.append(make_get_request(session, url_srps, task_name=f"GET Task SRPs List-{i+1}"))

        # Category 9: Performance - Array Categories (5 calls)
        url_perf_array_cat = f"{BASE_URL}/performance/Array/{SYMMETRIX_ID}/category"
        for i in range(5):
            get_tasks.append(make_get_request(session, url_perf_array_cat, task_name=f"GET Task Perf Array Cat-{i+1}"))

        # Category 10: Performance - FE Director Keys (5 calls)
        # This endpoint lists keys (director IDs) for which performance data is available.
        url_perf_fe_dir_keys = f"{BASE_URL}/performance/FEDirector/keys?symmetrixId={SYMMETRIX_ID}"
        for i in range(5):
            get_tasks.append(make_get_request(session, url_perf_fe_dir_keys, task_name=f"GET Task Perf FE Dir Keys-{i+1}"))
            
        # --- Run all tasks concurrently ---
        logger.info("--- Starting all POST Requests Concurrently ---")
        post_results = await asyncio.gather(*post_tasks)
        logger.info("--- Starting all GET Requests Concurrently ---")
        get_results = await asyncio.gather(*get_tasks)

        # --- Process and Log Summary Results ---
        logger.info("\n--- POST Results Summary ---")
        total_post_duration = 0
        successful_posts = 0
        for i, result in enumerate(post_results):
            duration = result.get('duration', 0)
            total_post_duration += duration
            status = result.get('status_code', 'Unknown')
            if "error" not in result and status not in ["ClientError", "Exception", "JSONDecodeError"] and isinstance(status, int) and status < 400 :
                successful_posts +=1
                logger.info(f"POST Task-{i+1} Success: Status {status}, Duration: {duration:.4f}s, Response (snippet): {str(result.get('data'))[:100]}...")
            else:
                logger.warning(f"POST Task-{i+1} Failed/Errored: Status {status}, Duration: {duration:.4f}s. Details in earlier logs.")
                if 'payload' in result:
                    logger.debug(f"POST Task-{i+1} Failed Payload: {json.dumps(result.get('payload'))}")
        if post_results:
            avg_post_duration = total_post_duration / len(post_results)
            logger.info(f"Total POSTs: {len(post_results)}, Successful: {successful_posts}, Failed/Errored: {len(post_results) - successful_posts}, Avg Duration: {avg_post_duration:.4f}s")
        else: logger.info("No POST tasks run.")

        logger.info("\n--- GET Results Summary ---")
        total_get_duration = 0
        successful_gets = 0
        for i, result in enumerate(get_results):
            duration = result.get('duration', 0)
            total_get_duration += duration
            status = result.get('status_code', 'Unknown')
            if "error" not in result and status not in ["ClientError", "Exception", "JSONDecodeError"] and isinstance(status, int) and status < 400:
                successful_gets += 1
                logger.info(f"GET Task Index-{i} Success: Status {status}, Duration: {duration:.4f}s, Response (snippet): {str(result.get('data'))[:100]}...")
            else:
                logger.warning(f"GET Task Index-{i} Failed/Errored: Status {status}, Duration: {duration:.4f}s. Details in earlier logs.")
        if get_results:
            avg_get_duration = total_get_duration / len(get_results)
            logger.info(f"Total GETs: {len(get_results)}, Successful: {successful_gets}, Failed/Errored: {len(get_results) - successful_gets}, Avg Duration: {avg_get_duration:.4f}s")
        else: logger.info("No GET tasks run.")

    logger.info(f"Script execution finished. Log file: {LOG_FILE}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Script execution cancelled by user (KeyboardInterrupt).")
    except Exception as e:
        logger.critical(f"Critical unhandled error in script execution: {e}", exc_info=True)
