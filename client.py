import glob
import logging
import os
import signal
import sys
import time
from threading import current_thread, Lock
from constants import LOGFILE, N_NORMAL_WORKERS, N_FILES, IS_RAFT, RAFT_CRASH_PORT, RAFT_PORTS, DATA_PATH, RAFT_JOIN_PORT
from mrds import MyRedis
from worker import WcWorker
from saver import Saver

workers = []

def sig_handler(signum, frame):
  for w in workers:
    w.kill()
    print("Killed worker")
  logging.info('Bye!')
  sys.exit()


if __name__ == "__main__":
  # Clear the log file
  open(LOGFILE, 'w').close()
  logging.basicConfig(# filename=LOGFILE,
                      level=logging.DEBUG,
                      force=True,
                      format='%(asctime)s [%(threadName)s] %(levelname)s: %(message)s')
  thread = current_thread()
  thread.name = "client"
  logging.debug('Done setting up loggers.')
  t0 = time.time()
  # signal.signal(signal.SIGTERM, sig_handler)
  signal.signal(signal.SIGINT, sig_handler)

  for i in range(N_NORMAL_WORKERS):
    workers.append(WcWorker())

  # Wait for workers to finish processing all the files
  if(not IS_RAFT):
    lua_path = os.path.join(os.getcwd(),"mylib.lua")
    os.system(f"cat {lua_path} | redis-cli -a pass -x FUNCTION LOAD REPLACE")
    rds = MyRedis()
    for i, w in enumerate(workers):
      w.create_and_run(rds=rds)

    logging.debug('Created all the workers')
    for iter, file in enumerate(glob.glob(DATA_PATH)):
      rds.add_file(file)
      
    # TODO: Create a thread that creates a checkpoint every N seconds
    rds.rds.bgsave()
    time.sleep(6)
    
    saver = Saver()
    saver.create_and_run(rds=rds)
    
    loki = True
    while loki:
      try: 
        loki = rds.is_pending()
        rds.restart(down_time=5, down_port=-1, instance_port=-1)
        time.sleep(6)
      except:
        continue

  elif(IS_RAFT):
    os.system(f"bash configure_redis.sh {' '.join(RAFT_PORTS)}")
    time.sleep(5)
    rds = MyRedis()
    for i, w in enumerate(workers):
      w.create_and_run(rds=rds, data_dir=DATA_PATH, workers_cnt=N_NORMAL_WORKERS, worker_id=i)

    time.sleep(2)
    rds.restart(down_time=8, down_port=RAFT_CRASH_PORT, instance_port=RAFT_JOIN_PORT)
    while rds.get_flag() != N_NORMAL_WORKERS:
      time.sleep(2)

  # Kill all the workers
  for w in workers:
    w.kill()
  if IS_RAFT==False:
    saver.kill()

  # Wait for workers to exit
  while True:
    try:
      pid_killed, status = os.wait()
      logging.info(f"Worker-{pid_killed} died with status {status}!")
    except:
      break

  for word, c in rds.top(3):
    logging.info(f"{word.decode()}: {c}")
  print(time.time()-t0)