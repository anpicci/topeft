import subprocess

def delete_condor_jobs_in_range(first_job_id, last_job_id):
    # Convert the base IDs into integers for looping
    first_base = int(first_job_id)
    last_base = int(last_job_id)
    
    # Loop through each job ID in the range
    for job_id in range(first_base, last_base + 1):
        try:
            # Execute the condor_rm command to remove the job
            result = subprocess.run(['condor_rm', str(job_id)], capture_output=True, text=True)
            if result.returncode == 0:
                print(f"Successfully deleted job {job_id}")
            else:
                print(f"Failed to delete job {job_id}: {result.stderr}")
        except subprocess.CalledProcessError as e:
            print(f"Error removing job {job_id}: {e}")

if __name__ == "__main__":
    from topeft.modules.logging_config import configure_topeft_logging
    configure_topeft_logging("INFO")

    # Specify the first and last job ID (as an example, update with actual IDs)
    first_job_id = "113935"
    last_job_id = "113960"
    
    delete_condor_jobs_in_range(first_job_id, last_job_id)
