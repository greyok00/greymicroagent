# Master Guide — linux systemctl restart service

> **Executive Brief:** How to Start, Stop and Restart Services in Linux Using systemctl Command Last Updated : 23 Jul, 2025 System services play a crucial role in the functioning of a Linux system, handling various tasks and processes in the background. systemctl is a powerful command-line tool that allows users to manage these services effectively. *(per geeksforgeeks.org)* In this article, we will explore the basics of using systemctl to start, stop, restart, enable, disable and display status of services in a Linux environment. *(per geeksforgeeks.org)* This command is used to control the systemd system and service manager, which is a central component in modern Linux distributions. systemctl [command] [unit] Here, command: Action to be performed (e.g., start, stop, restart, enable, disable). unit: The service or unit to be affected. *(per geeksforgeeks.org)*

Compiled live from 2 accepted source(s) via the searx.space and direct-engine search ladder and a headless browser, filtered by the two-stage relevance gate. Every section carries its source;

---

## 1. Deep-Dive Overview & Context
How to Start, Stop and Restart Services in Linux Using systemctl Command Last Updated : 23 Jul, 2025 System services play a crucial role in the functioning of a Linux system, handling various tasks and processes in the background. systemctl is a powerful command-line tool that allows users to manage these services effectively. (geeksforgeeks.org)

In this article, we will explore the basics of using systemctl to start, stop, restart, enable, disable and display status of services in a Linux environment. (geeksforgeeks.org) This command is used to control the systemd system and service manager, which is a central component in modern Linux distributions. systemctl [command] [unit] Here, command: Action to be performed (e.g., start, stop, restart, enable, disable). unit: The service or unit to be affected. (geeksforgeeks.org) Example: sudo systemctl status mariadb Command Status How to restart a System Service in Linux Syntax: sudo systemctl restart service.service The command restart serves for restarting the service in execution. (geeksforgeeks.org) Example: sudo systemctl restart mariadb Command Restart How to Enable a System Service in Linux Syntax: sudo systemctl enable name_service.service The enable command serves for executing the service since the initialization if consists of one or more units or unit instances. (geeksforgeeks.org)

Search coverage for this run — decomposition: 1 results; general: 8 results; relevance-gate: 7 results.

## 2. Full Technical & Feature Breakdown
### How to Start, Stop and Restart Services in Linux Using systemctl Command - GeeksforGeeks


How to Start, Stop and Restart Services in Linux Using systemctl Command
Last Updated :
23 Jul, 2025

System services play a crucial role in the functioning of a Linux system, handling various tasks and processes in the background. systemctl is a powerful command-line tool that allows users to manage these services effectively. In this article, we will explore the basics of using systemctl to start, stop, restart, enable, disable and display status of services in a Linux environment.

What is systemctl?

Before diving into service management, it's essential to understand the basics systemctl. This command is used to control the systemd system and service manager, which is a central component in modern Linux distributions.

systemctl [command] [unit]

Here,

command: Action to be performed (e.g., start, stop, restart, enable, disable).
unit: The service or unit to be affected.

Systemctl is a controller or utility of Systemd (an init system with a set of programs executed in the background), with auxiliary in manage services, These commands are executed in mode root if you aren't mode rooting the system, requesting the password of root.

What is a service?

A service in computing is a background process that performs specific tasks and functions without user intervention. Services often start automatically during system boot and run continuously to provide functionalities such as web serving, file sharing, or system monitoring. They are managed by the operating system and can be started, stopped, or restarted as needed. Services help ensure essential operations are consistently available. Examples include web servers like Apache, database servers like MySQL, and system logging services.

What is a daemon?

A daemon is a background process that runs continuously on a Linux or Unix system. It performs tasks without direct user interaction, often starting automatically at boot. Common examples include web servers, database servers, and system monitoring tools. Daemons usually have names ending with "d", like httpd or sshd. They help manage system functions and services efficiently.

What is the init system?

The init system is the first process that runs when a Linux system boots up and is responsible for initializing the system. It manages system services and processes, handling their start, stop, and restart. Common init systems include SysVinit, Upstart, and systemd. The init system ensures that all necessary services are running correctly and manages dependencies between them. It continues to run in the background to monitor and manage system processes throughout the system's operation.

Units in systemd

In systemd, units are the basic objects that systemd manages and controls. They represent system resources such as services, timers, devices, and mount points. Each unit is defined by a configuration file with a specific suffix, like .service for services or .timer for timers. Units can be started, stopped, enabled, or disabled using systemctl commands. They are essential for defining how the system boots and manages various processes and resources.

.service units in systemd

Systemd .service units are configuration files used to manage services on Linux systems. They define how and when services should be started, stopped, and restarted. Each .service file contains details like the service's name, description, and the command to run. These files are typically located in /etc/systemd/system or /lib/systemd/system. Managing them involves commands like systemctl start, systemctl stop, and systemctl enable.

How to find all the systemd units in the system?

To list available systems units or to List all Services in Linux we use the following command:

systemctl list-unit-files --type service -all
How to Start a System Service in Linux

Syntax:

sudo systemctl start service.service

The command start serves for starting (activate) one or more units specified on the command line.

Example:

sudo systemctl start mariadb

Command Start
How to Stop a System Service in Linux

Syntax:

sudo systemctl stop service.service

The command stop serves for stopping the service or (deactivate) one or more units specified on the command line.

Example:

sudo systemctl stop mariadb

Command Stop and Status
How to Display Status of a System Service in linux

Syntax:

sudo systemctl status service.service

The command status serves to check the status of the service. Show terse runtime status information about one or more units, followed by the most recent log data from the journal. If no units are specified, show system status.

Example:

sudo systemctl status mariadb

Command Status
How to restart a System Service in Linux

Syntax:

sudo systemctl restart service.service

The command restart serves for restarting the service in execution. Stop and then start one or more units specified on the command line. If the units are not running yet, they will be started.

Example:

sudo systemctl restart mariadb

Command Restart
How to Enable a System Service in Linux

Syntax:

sudo systemctl enable name_service.service

The enable command serves for executing the service since the initialization if consists of one or more units or unit instances. This will create a set of symlinks, as encoded in the [Install] sections of the indicated unit files. the system manager configuration is reloaded (in a way equivalent to daemon-reload), in order to ensure the changes are taken into account immediately.

Example

sudo systemctl enable mariadb

Command Enable
Command Status
How to Disable a System Service in Linux

Syntax:

sudo systemctl disable name_service.service

The disable command serves for withdrawing the service since the initialization of one or more units. This removes all symlinks to the unit files backing the specified units from the unit configuration directory and hence undoes any changes made by enabling or link.

Example:

sudo systemctl disable mariadb

Command Disable
Command Status
Shutdown or reboot the system using systemctl

Reboot the System: It instructs systemd to restart the entire system. All services are stopped, and the system goes through a complete shutdown process before restarting.

sudo systemctl reboot

Shut Down the System: It tells systemd to power off the machine. All services and processes are stopped, and the system is safely powered down.

sudo systemctl shutdown
journalctl

journalctl is a command used in Linux systems to query and display logs from the systemd journal, which is a system service that collects and stores logging data. Here’s a simple guide on how to use journalctl:

journalctl -n 10 is used to display the last 10 entries (lines) from the systemd journal. Here's a breakdown of what each part of the command does:

journalctl: Invokes the journalctl command, which is used to query and display logs from the systemd journal.
-n 10: Specifies the number of lines to display. In this case, -n 10 instructs journalctl to show the last 10 entries from the journal.
journalctl -n 10
Securing a service using systemd

Securing a service using systemd is an essential practice to safeguard your system against potential vulnerabilities and unauthorized access. Here's a simplified guide on how to accomplish this:

1. Understand Service Unit Files

Service Configuration: Each service in systemd is managed by a unit file, typically located in /etc/systemd/system/. These files define how the service operates, including its start-up behavior, resource limits, and security settings.

2. Restrict Service Permissions

User and Group Permissions: Specify the user and group under which the service runs. Avoid using the root user whenever possible to minimize the impact of security breaches.

3. Utilize systemd Security Features

PrivateTmp: Enable private /tmp and /var/tmp directories for the service to prevent information leakage between different services.
ProtectSystem and ProtectHome: Set these options to restrict access to system directories and user home directories, respectively, to enhance system security.
ReadOnlyPaths and ReadWritePaths: Specify which directories the service can read from or write to. Limiting write access can prevent unintended modifications to critical files.

4. Limit Resource Usage

Limit CPU and Memory: Use CPUQuota and MemoryLimit options to restrict the service's CPU and memory usage, preventing resource exhaustion attacks.

5. Enable Network Controls

Restrict Network Access: Utilize RestrictAddressFamilies, IPAddressAllow, and IPAddressDeny options to control network access for the service, limiting its exposure to potential threats.

6. Set File System Permissions

File System Permissions: Ensure that the service's files and directories have appropriate permissions (chmod) and ownership (chown) to prevent unauthorized access.

7. Regularly Update and Monitor

Keep System Updated: Regularly update your system and service software to patch security vulnerabilities and ensure that your security measures remain effective.
Monitor Logs: Monitor systemd journal logs (journalctl) for any suspicious activities or security-related events, and take appropriate action if necessary.
Conclusion

We discussed systemctl which is a vital command-line tool for managing system services in Linux, playing a crucial role in tasks such as starting, stopping, restarting, enabling, and disabling services. This article provided a comprehensive guide to systemctl, covering its syntax and key commands. From listing available systemd units to enabling or disabling automatic startup, each command contributes to effective service management. The article also addressed common questions, offering practical solutions for tasks such as checking service status, starting, stopping, and restarting services, and enabling or disabling automatic startup. Overall, understanding and mastering systemctl commands are essential for Linux administrators to ensure the stability and optimal performance of their systems.

Comment

R

raulbrunolima
4
Explore
Basics
Introduction to Linux
Architecture of Linux
File Management in Linux
3 min read
Directory Management in Linux
3 min read
Permissions & Ownership
User Management in Linux
7 min read
Group Management in Linux
File Permission and Ownership Commands in Linux
2 min read
chmod Command in Linux
4 min read
chown Command in Linux
6 min read
Process & Networking
ps Command in Linux
7 min read
top Command in Linux
8 min read
kill Command in Linux
5 min read
ifconfig Command in Linux
7 min read
ip Command in Linux
4 min read
Ping Command in Linux
4 min read
Netstat command in Linux
4 min read
Services & System Management
Boot Process with Systemd in Linux
4 min read
Systemd and its Components in Linux
2 min read
Controling systemd Services on Remote Linux Server
2 min read
Managing System Services in Linux - systemctl Command
3 min read
scp Command for Secure File and Folder Transfer
6 min read
Shell Scripting & Bash Scripting
Introduction to Linux Shell and Shell Scripting
7 min read
Understanding Terminal, Console, Shell and Kernel
4 min read
Writing and executing shell scripts
2 min read
Shell Scripting - Shell Variables in Linux
Bash Scripting - Working of Bash Scripting
4 min read
Bash Script - Define Bash Variables and its types
8 min read
Bash Script - Difference between Bash Script and Shell Script
Corporate & Communications Address:
A-143, 6th Floor, Sovereign Corporate Tower, Sector- 136, Noida, Uttar Pradesh (201305)
Registered Address:
K 061, Tower K, Gulshan Vivante Apartment, Sector 137, Noida, Gautam Buddh Nagar, Uttar Pradesh, 201305
Software and Tools
Courses
ML and Data Science
DSA and Placements
C++
@GeeksforGeeks, Sanchhaya Education Private Limited, All rights reserved



### How to Start, Stop, and Restart Services in Linux


Home » KB » SysAdmin » How to Start, Stop, and Restart Services in Linux

How to Start, Stop, and Restart Services in Linux
By
Sara Zivanov
Published:
December 17, 2025
Topics:
Apache, Commands, Linux

Using the systemctl command, Linux provides fine-grained control over system services through systemd. Services can be turned on, off, restarted, reloaded, as well as enabled or disabled at boot.

This guide will show you how to start, stop, and restart services in Linux.

Prerequisites

Access to a user account with sudo or root privileges.
Access to the terminal.
A Linux system.
What Is systemctl?

systemctl is an essential command-line tool for system administrators and users on Linux systems utilizing systemd, the default init system for many Linux distributions.

systemctl provides an efficient way to manage Linux services. Services in Linux are background processes crucial for the proper functioning of the operating system and various applications.

The systemctl syntax is:

systemctl [options] [command] [unit] 
Copy

The syntax consists of:

systemctl. The command that interacts with systemd and manages services.
[options]. Optional arguments that modify the systemctl command behavior. 
[command]. The action to be performed on the specified units. 
[unit]. Units to be acted upon, like services, sockets, targets, etc. If no units are specified, the command applies to all units of the specified type.
systemctl vs. service

systemctl and service are command-line tools used to manage services in Linux. However, they are associated with different init systems. Init is the initialization process, the first process that starts when the computer boots up. It is responsible for initializing the system and starting other processes and services.

While systemctl is used to manage Linux services that use systemd as their init system, service is a legacy command-line tool used to manage services in Linux distributions that use traditional init systems like SysVinit or Upstart.

systemctl provides more advanced features than the traditional service command. However, both commands are available on modern Linux distributions for compatibility reasons.

How to Start a Service

To start a service in Linux, type in the following:

sudo systemctl start [service-name]
Copy

For instance, the command to start the Apache service is:

sudo systemctl start apache2
Copy

The command has no output. Verify the service is active with:

sudo systemctl status apache2
Copy

The output shows the service is active (running).

To configure a service to start when the system boots, use the command:

sudo systemctl enable [service-name]
Copy

For example, enable Apache to start with the system boot with:

sudo systemctl enable apache2
Copy

Note: Different Linux distributions sometimes have different names for one service.

How to Stop a Service

To stop an active service in Linux, use the following command:

sudo systemctl stop [service-name]
Copy

For example, to stop Apache, execute:

sudo systemctl stop apache2
Copy

The command has no output. Check whether the service stopped running:

sudo systemctl status apache2
Copy

The output shows the service is inactive (dead).

Another way to ensure the service is not active is to prevent it from starting on boot. Use the command:

sudo systemctl disable [service-name]
Copy

For example:

sudo systemctl disable apache2
Copy
How to Restart a Service

To restart the service in Linux, use the command:

sudo systemctl restart [service-name]
Copy

To restart Apache, use:

sudo systemctl restart apache2
Copy

The command has no output. Verify the status with:

sudo systemctl status apache2
Copy
How to Reload a Service

To restart a service, you need to stop it completely and then start it again. On the other hand, reloading a service reloads its configuration files and applies any changes without stopping the service.

To reload a service, run:

sudo systemctl reload [service-name]
Copy

For instance, reload Apache with:

sudo systemctl reload apache2
Copy

The command does not provide any output. Confirm the service is running with:

sudo systemctl status apache2
Copy

The output shows the service is active and running.

Note: For information on how to reload the systemd manager configuration, refer to our guide to the systemctl daemon-reload command.

Conclusion

This article explained how systemctl works. It also elaborated on how to start, stop, restart, and reload a service in Linux.

Next, learn about important Linux commands.

Was this article helpful?
YesNo

Contents

What Is systemctl?
systemctl vs. service
How to Start a Service
How to Stop a Service
How to Restart a Service
How to Reload a Service
Next you should read
SysAdmin
SCP Command in Linux {13 Examples}
SysAdmin
How To Use grep Command In Linux/UNIX
SysAdmin
How to Use mkdir Command to Make or Create a Linux Directory
Networking SysAdmin
How to Use IP Command in Linux with Examples
How to Deploy AI Agents on an Ubuntu Server
Terraform taint Command Explained
kubectl apply Command Explained
terraform console Command: Usage and Examples
Terraform depends_on Meta Argument Explained
CLOUD SERVICES
Object Storage
Cloud Servers In Europe

## 3. Comparative Data & Specs
**No comparative tables captured.** All table data: DATA NOT CAPTURED.

## 4. Complete Actionable Steps / Execution Guide
DATA NOT CAPTURED — no procedure-shaped steps were present in the captured sources. Steps are never fabricated from unrelated prose.

## Research limitations
The two-stage relevance gate (deterministic pre-filter + semantic judge) removed or quarantined the following pages; they do NOT contribute any prose, facts, tables, citations, or images to this guide.

- **deprioritized** — https://www.linode.com/docs/guides/introduction-to-systemctl/ (page cap 2 reached)
- **deprioritized** — https://linuxize.com/post/systemctl-command-in-linux/ (page cap 2 reached)
- **deprioritized** — https://www.akamai.com/cloud/guides/introduction-to-systemctl (page cap 2 reached)
- **deprioritized** — https://www.geeksforgeeks.org/linux-unix/systemctl-in-unix/ (page cap 2 reached)
- **deprioritized** — https://linuxize.com/post/reboot-linux-using-command-line/ (page cap 2 reached)

**Quality warnings:**
- thin run: only 2 accepted page(s) — the guide reports DATA NOT CAPTURED rather than padding

---

## 5. Primary Sources & Media Links
- [How to Start, Stop and Restart Services in Linux Using systemctl Command - GeeksforGeeks (relevance 100)](https://www.geeksforgeeks.org/linux-unix/start-stop-restart-services-using-systemctl-in-linux/)
- [How to Start, Stop, and Restart Services in Linux (relevance 100)](https://phoenixnap.com/kb/start-stop-restart-linux-services)
