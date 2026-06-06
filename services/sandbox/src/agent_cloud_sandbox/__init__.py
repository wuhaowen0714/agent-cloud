import os

# gRPC fork-handler hygiene: the bash tool forks subprocesses inside the aio
# server, which makes gRPC spam fork/poll/Ixxxx lines to stderr. Disable fork
# support and quiet verbosity so that noise can't contaminate tool output. Must
# run before any grpc import in this package. (See sandbox tools _bash + spec §11.)
os.environ.setdefault("GRPC_ENABLE_FORK_SUPPORT", "0")
os.environ.setdefault("GRPC_VERBOSITY", "ERROR")
