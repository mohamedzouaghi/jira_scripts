"""This script updates JIRA issue fields according to predefined rules. 
For instance, if all subtasks of a story are in Done status, the story
status is modified to Done status as well.
The script uses a robot account with suitable previleges to connect to JIRA
In order to add a project to the scope of this script, the project code
should be added to config/config.yaml
Script is meant to be run from a cron or equivalent (Like Jenkins for instance)
Original Author: mz@noor-it.com



Modules that are needed in order to run the script are:
pip install jira
pip install pyyaml

Usage Example: update_issues_fields.py -a account@domain.com -k API_KEY_VALUE_FROM_JIRA --no-d
--no-d means no dryrun, which means issues will have their field updated.
"""

import argparse
import logging
import yaml

from jira import JIRA

logging.basicConfig(level=logging.DEBUG, format='%(levelname)-8s %(asctime)-26s %(filename)s %(message)s')
global_logger = logging.getLogger(__name__)


JIRA_SERVER = 'https://noor-it.atlassian.net'

YAML_PROJECT_KEYWORD = 'projects'

# Possible status values. Always keep uppercase.
TO_DO = 'TO DO'
BLOCKED = 'BLOCKED'
IN_PROGRESS = 'IN PROGRESS'
DONE = 'DONE'
ACCEPTED = 'ACCEPTED'

MODIFIABLE_STATUS = [TO_DO, BLOCKED, IN_PROGRESS, DONE]
NON_MODIFIABLE_STATUS = [ACCEPTED]
SUPPORTED_STATUS = MODIFIABLE_STATUS + NON_MODIFIABLE_STATUS

RULE_POLICY_AT_LEAST_ONE = 'at_least_one'
RULE_POLICY_ALL = 'all'
SUPPORTED_RULE_POLICY = {RULE_POLICY_AT_LEAST_ONE, RULE_POLICY_ALL}


STATUS_RULES = [
    # Structure of a STATUS_RULES entry is:
    # (TARGET_STATUS, (RULE_POLICY, {POSSIBLE_STATUSES}))
    (DONE, (RULE_POLICY_ALL, {DONE, ACCEPTED})),
    (TO_DO, (RULE_POLICY_ALL, {TO_DO})),
    # If a least 1 subtask is blocked, story should switch to Blocked
    (BLOCKED, (RULE_POLICY_AT_LEAST_ONE, {BLOCKED})),
    (IN_PROGRESS, (RULE_POLICY_AT_LEAST_ONE, {IN_PROGRESS})),
    # TODO(mz@): Add case when story has 1 subtask to do and one diffeerent than Todo
]


def updateStatusIfNeeded(jira, issueLevelTwo, dryrun):
  """
  Function updates the issues status of a level two issue according to predefined rules in STATUS_RULES.
  Function takes a JIRA issue level two, meaning not an Epic nor a subtask and verify whether one of
  the rules defined at STATUS_RULES is applicable or not. If it's applicable, issue status is updated 
  accordignly. Example: If all subtasks of a story are in Blocked status, the story status is
  swithed to Blocked.
  IMOPTANT: The rules defined at STATUS_RULES are applied by priority from higher level to lower level.
  If more than a rule is applicable, the higher applicable one will be applied.

  Arguments:
    issueLevelTwo: JIRA issue at level two. Valid example: Story, Bug, Spike.

  Return:
    A boolean. True if an update was made to the issue, false otherwise.

  """
  issueStatus = issueLevelTwo.fields.status.name
  newStatus = issueStatus
  didStatusChanged = False

  if issueStatus.upper() in MODIFIABLE_STATUS:
    for status, rule in STATUS_RULES:
      didStatusChanged = False
      rulePolicy, possibleStatus = rule
      if isRuleApplicable(issueLevelTwo, rulePolicy, possibleStatus):
        newStatus = status
        if newStatus != issueStatus and not dryrun:
          # Below Should only be deactivated for debug purpose. To be reactivated before commiting. 
          jira.transition_issue(issueLevelTwo.key, newStatus)
          didStatusChanged = True
        break
  global_logger.info(
      'Issue ['+issueLevelTwo.key +'] old status/new status: ['+ issueStatus +'/'+ newStatus +'] status change result:' + str(didStatusChanged))
  return issueStatus != newStatus


def isRuleApplicable(issue, rulePolicy, possibleStatus):
  """
  According to issue status, Rule Policy and Possible status, returns whether the rulePolicy is applicable to the specific status.
  RULE_POLICY_ALL means that all of the issue subtask should be in one of the possibleStatus,
  in the other hand, RULE_POLICY_AT_LEAST_ONE means that at least one of the issue subtask should be in possibleStatus.
  
  Arguments:
    issue: JIRA issue that has a issue.fields.subtasks.
    rulePolicy: String. One of the values defined in SUPPORTED_RULE_POLICY.
    possibleStatus: A list of values defined in SUPPORTED_STATUS.

  Return:
    True, a rule policy is fulfilled, false otherwise.

  """
  subtasks = issue.fields.subtasks
  if rulePolicy == RULE_POLICY_ALL:
    for subt in subtasks:
      if subt.fields.status.name.upper() not in possibleStatus:
        return False
    return True 
  elif rulePolicy == RULE_POLICY_AT_LEAST_ONE:
    for subt in subtasks:
      if subt.fields.status.name.upper() in possibleStatus:
        return True
    return False
  else:
    # TODO(mz@): change this to raise exception and catch it from called
    global_logger.warn('Warning: Not supported rulePolicy:' + str(rulePolicy))
    return False



def initJira(account, key, server):
  jiraInstance = JIRA(
    # TODO(mz@): To modify the key so it can be read from a file and not from command line
    basic_auth=(account, key), 
    options={'server': server}
  )
  return jiraInstance


def getProjectIDs(filePath):
  """
  Returns the JIRA project codes that are found in yaml file within the projects field.

  Arguments:
    filePath: String. Relative or absolute path of the YAML file.

  Return:
    List of JIRA project codes. If no project code is found, an empty list is returned.

  """
  with open(filePath) as file:
    documents = yaml.full_load(file)

    for key, projectsIDs in documents.items():
      if key == YAML_PROJECT_KEYWORD:
        return projectsIDs.split(' ')
    # If this point is reached, means keyword YAML_PROJECT_KEYWORD wasn't found

  return []



def main():
  parser = argparse.ArgumentParser()
  parser.add_argument('-a', '--account', required=True, 
    help='JIRA robot account which should be used to interact with issues. Account should have appropriate permissions to perform the expected actions. Valid example: abc@cde.com')
  parser.add_argument('-k', '--key', required=True, help='JIRA robot API key that is meant to be used for authentification')
  parser.add_argument('-d', '--dryrun', required=False, dest='dryrun', action='store_true',
                      help='If set to true no issues will be updated.')
  parser.add_argument('--no-d', '--no-dryrun', required=False, dest='dryrun', action='store_false',
                      help='If set to false no issues will be updated.')
  parser.set_defaults(dryrun=True)
  args = parser.parse_args()

  projectIDs = getProjectIDs('config/config.yaml')
  if len(projectIDs) == 0:
    global_logger.critical('Mandatory keyword ['+ YAML_PROJECT_KEYWORD +'] wasn\'t found in file ['+ filePath +']')


  jira = initJira(args.account, args.key, JIRA_SERVER)
  
  global_logger.info('Dryrun mode:' + str(args.dryrun))

  for projectId in projectIDs:
    # TODO(mz@): To wrap the project id with something to make it more robust
    global_logger.debug('Start Performing verification/actions for project [' + projectId + ']')
    try:
      issues_in_project = jira.search_issues(' project = "' + projectId + '"  AND SPRINT in openSprints() and sprint not in futureSprints() ', maxResults=1000)
    except Exception as e:
      global_logger.error('Error happened when querying JIRA:\n%s' % e)
      continue

    possibleChanges = 0
    performedChanges = 0
    
    for issue in issues_in_project:
      possibleChanges += 1
      global_logger.debug('Performing verification/actions for [' + issue.key + '/' + issue.fields.issuetype.name +']')
      if updateStatusIfNeeded(jira, issue, args.dryrun):
        performedChanges += 1
    global_logger.info('End of operations: Number of possible changes:' + str(possibleChanges) + '\t Number of detected changes:' + str(performedChanges))
    
    
 
if __name__ == '__main__':
  main()
