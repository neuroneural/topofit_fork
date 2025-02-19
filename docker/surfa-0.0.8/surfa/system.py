import os
import sys
import platform
import subprocess as sp


def run(command, silent=False, background=False, executable='/bin/bash', log=None):
    """
    Runs a shell command and returns the exit code.

    Parameters
    ----------
    command : str
        Command to run.
    silent : bool
        Send output to devnull.
    background : bool
        Run command as a background process.
    executable : str
        Shell executable. Defaults to bash.
    log : str
        Send output to a log file.

    Returns
    -------
    int
        Command exit code.
    """

    # redirect the standard output appropriately
    if silent:
        std = {'stdout': sp.DEVNULL, 'stderr': sp.DEVNULL}
    elif not background:
        std = {'stdout': sp.PIPE, 'stderr': sp.STDOUT}
    else:
        std = {}  # do not redirect

    # run the command
    process = sp.Popen(command, **std, shell=True, executable=executable)
    if not background:
        # write the standard output stream
        if process.stdout:
            for line in process.stdout:
                decoded = line.decode('utf-8')
                if log is not None:
                    with open(log, 'a') as file:
                        file.write(decoded)
                sys.stdout.write(decoded)
        # wait for process to finish
        process.wait()

    return process.returncode


def collect_output(command, executable='/bin/bash'):
    """
    Collects the output of a shell command.

    Parameters
    ----------
    command : str
        Command to run.
    executable : str
        Shell executable. Defaults to bash.

    Returns
    -------
    tuple of (str, int)
        Tuple containing the command output and the corresponding exit code.
    """
    result = sp.run(command, stdout=sp.PIPE, stderr=sp.STDOUT, shell=True, executable=executable)
    return (result.stdout.decode('utf-8'), result.returncode)


def hostname(short=True):
    """
    Gets the system hostname.

    Parameters
    ----------
        short: Provide the short hostname. Defaults to True.
    """
    node = platform.node()
    if short:
        return node.split('.')[0]
    return node


def vmpeak():
    """
    Returns the peak memory usage of the process in kilobytes.

    Note: This only works on linux machines because itf requires `/proc/self/status`.
    """
    # TODO: switch to this (portable across platforms)
    # return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    procstatus = '/proc/self/status'
    if os.path.exists(procstatus):
        with open(procstatus, 'r') as file:
            for line in file:
                if 'VmPeak' in line:
                    return int(line.split()[1])
    return None


def fatal(message, retcode=1):
    """
    Prints an error message and exits or raises an exception if in interactive mode.

    Parameters
    ----------
    message : str
        Error message to print
    retcode : int
        Exit code. Defaults to 1.
    """
    import __main__ as main
    if hasattr(main, '__file__'):
        print(f'Error: {message}')
        sys.exit(retcode)
    else:
        raise Exception(message)
