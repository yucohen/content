import demistomock as demisto
from CommonServerPython import *

import requests
import traceback
from typing import Dict, Any
from datetime import datetime

# Disable insecure warnings
requests.packages.urllib3.disable_warnings()


""" CONSTANTS """

SECURITYSCORECARD_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
DATE_FORMAT = '%Y-%m-%dT%H:%M:%SZ'

""" CLIENT CLASS """


class Client(BaseClient):
    """Client class to interact with the service API

    This Client implements API calls, and does not contain any XSOAR logic.
    Should only do requests and return data.
    It inherits from BaseClient defined in CommonServer Python.
    Most calls use _http_request() that handles proxy, SSL verification, etc.
    For this  implementation, no special attributes defined
    """

    def get_portfolios(self) -> Dict[str, Any]:

        return self._http_request(
            'GET',
            url_suffix='portfolios'
        )

    def get_companies_in_portfolio(
        self,
        portfolio: str,
        grade: Optional[str],
        industry: Optional[str],
        vulnerability: Optional[str],
        issue_type: Optional[str],
        had_breach_within_last_days: Optional[int]
    ) -> Dict[str, Any]:

        request_params: Dict[str, Any] = {}

        if grade:
            request_params['grade'] = grade
        if industry:
            request_params['industry'] = str.upper(industry)
        if vulnerability:
            request_params['vulnerability'] = vulnerability
        if issue_type:
            request_params['issue_type'] = issue_type
        if had_breach_within_last_days:
            request_params['had_breach_within_last_days'] = had_breach_within_last_days

        return self._http_request(
            'GET',
            url_suffix=f'portfolios/{portfolio}/companies',
            params=request_params,
            error_handler=self.company_portfolio_error_handler
        )

    def get_company_score(self, domain: str) -> Dict[str, Any]:

        return self._http_request(
            'GET',
            url_suffix=f'companies/{domain}'
        )

    def get_company_factor_score(self, domain: str, severity_in: Optional[List[str]]) -> Dict[str, Any]:

        request_params: Dict[str, Any] = {}

        if severity_in:
            request_params['severity_in'] = severity_in

        return self._http_request(
            'GET',
            url_suffix=f'companies/{domain}/factors',
            params=request_params
        )

    def get_company_historical_scores(self, domain: str, _from: str, to: str, timing: str) -> Dict[str, Any]:

        request_params: Dict[str, Any] = {}

        if _from:
            request_params['from'] = _from

        if to:
            request_params['to'] = to

        if timing:
            request_params['timing'] = timing
        # API by default is set to daily
        else:
            request_params['timing'] = 'daily'

        return self._http_request(
            'GET',
            url_suffix=f'companies/{domain}/history/score',
            params=request_params)

    def get_company_historical_factor_scores(self, domain: str, _from: str, to: str, timing: str) -> Dict[str, Any]:

        request_params: Dict[str, Any] = {}

        if _from:
            request_params['from'] = _from
        if to:
            request_params['to'] = to
        if timing:
            request_params['timing'] = timing

        return self._http_request(
            'GET',
            url_suffix=f'companies/{domain}/history/factors/score',
            params=request_params
        )

    def create_grade_change_alert(
        self,
        email: str,
        change_direction: str,
        score_types: List[str],
        target: List[str]
    ) -> Dict[str, Any]:

        payload: Dict[str, Any] = {}
        if change_direction:
            payload["change_direction"] = change_direction

        if len(score_types) > 0:
            payload["score_types"] = score_types

        if len(target) > 0:
            payload["target"] = target

        return self._http_request(
            'POST',
            url_suffix=f"users/by-username/{email}/alerts/grade",
            json_data=payload
        )

    def create_score_threshold_alert(
        self,
        email: str,
        change_direction: str,
        threshold: int,
        score_types: List[str],
        target: List[str]
    ) -> Dict[str, Any]:

        payload: Dict[str, Any] = {}
        if change_direction:
            payload["change_direction"] = change_direction

        threshold_arg = arg_to_number(arg=threshold, arg_name='threshold', required=True)
        payload["threshold"] = threshold_arg

        if len(score_types) > 0:
            payload["score_types"] = score_types

        if len(target) > 0:
            payload["target"] = target

        return self._http_request(
            'POST',
            url_suffix=f"users/by-username/{email}/alerts/score",
            json_data=payload
        )

    def delete_alert(self, email: str, alert_id: str, alert_type: str) -> None:

        return self._http_request(
            "DELETE",
            url_suffix=f"users/by-username/{email}/alerts/{alert_type}/{alert_id}",
            return_empty_response=True
        )

    def get_alerts_last_week(self, email: str, portfolio_id: Optional[str]) -> Dict[str, Any]:

        query_params = {}

        if portfolio_id:
            query_params["portfolio"] = portfolio_id

        return self._http_request(
            "GET",
            url_suffix=f"users/by-username/{email}/notifications/recent",
            params=query_params
        )

    def get_domain_services(self, domain: str) -> Dict[str, Any]:

        return self._http_request(
            'GET',
            url_suffix=f"companies/{domain}/services"
        )

    def fetch_alerts(self, username: str, page_size: int):

        query_params: Dict[str, Any] = {}

        query_params["username"] = username
        query_params["page_size"] = page_size

        # Default parameters to sort by descending date
        # ?sort=date&order=desc&
        query_params["sort"] = "date"
        query_params["order"] = "desc"

        return self._http_request(
            "GET",
            url_suffix=f"users/by-username/{username}/notifications/recent",
            params=query_params
        )

    @staticmethod
    def company_portfolio_error_handler(res) -> None:

        try:
            json_resp = res.json()
            requested_portfolio = json_resp.get("error").get("data").get("portfoliosRequested")[0]
            error_message = f"""Portfolio '{requested_portfolio}' doesn't exist.
Please run !securityscorecard-portfolios-list to see available Portfolios and try again.
            """
        except Exception:
            raise DemistoException("Response error is invalid JSON.")

        raise DemistoException(error_message, exception=None, res=None)


""" HELPER FUNCTIONS """


def incidents_to_import(alerts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:

    """
    Helper function to filter events that need to be imported
    It filters the events based on the `created_at` timestamp.
    Function will only be called if the SecurityScorecard API returns more than one alert.

    :type ``events``: ``List[Dict[str, Any]]``

    :return
        Events to import

    :rtype
        ``List[Dict[str, Any]]``
    """

    # Check for existence of last run
    # When integration runs for the first time, it will not exist
    # Set 3 days by default if the first fetch parameter is not set
    if demisto.getLastRun().get("last_run"):
        last_run = int(demisto.getLastRun().get("last_run"))
    else:
        days_ago_arg = params.get("first_fetch")  # type: ignore

        if not days_ago_arg:
            days_ago_str = "3 days"
        else:
            days_ago_str = days_ago_arg

        fetch_days_ago = arg_to_datetime(days_ago_str, arg_name="first_fetch", required=False)

        # to prevent mypy incompatible assignment
        assert fetch_days_ago is not None
        valid_fetch_days_ago: datetime = fetch_days_ago

        demisto.debug(f"getLastRun is None in integration context, using parameter 'first_fetch' value '{days_ago_arg}'")
        demisto.debug(f"{days_ago_str} => {valid_fetch_days_ago}")

        last_run = int(valid_fetch_days_ago.timestamp())

    demisto.debug(f"Last run timestamp: {last_run}")

    incidents_to_import: List[Dict[str, Any]] = []

    alerts_returned = len(alerts)
    demisto.debug(f"Number of alerts found: {alerts_returned}")
    # Check if there are more than 0 alerts
    if alerts_returned > 0:

        # The alerts are sorted by descending date so first alert is the most recent
        most_recent_alert = alerts[0]

        # casting to str to prevent mypy error:
        # Argument 1 to "strptime" of "datetime" has incompatible type "Optional[Any]"; expected "str"
        most_recent_alert_created_date = str(most_recent_alert.get("created_at"))

        most_recent_alert_timestamp = \
            int(datetime.strptime(most_recent_alert_created_date, SECURITYSCORECARD_DATE_FORMAT).timestamp())
        demisto.debug(f"Setting last runtime as alert most recent timestamp: {most_recent_alert_timestamp}")
        demisto.setLastRun({
            'last_run': most_recent_alert_timestamp
        })

        for alert in alerts:

            alert_created_at = str(alert.get("created_at"))
            alert_timestamp = int(datetime.strptime(alert_created_at, SECURITYSCORECARD_DATE_FORMAT).timestamp())

            alert_id = alert.get("id")

            debug_msg = f"""
            last_run: {last_run}, alert_timestamp: {alert_timestamp},
            should import alert '{alert_id}'? (last_run < alert_timestamp): {(last_run < alert_timestamp)}
            """
            demisto.debug(debug_msg)

            if alert_timestamp > last_run:
                incident = {}
                incident["name"] = f"SecurityScorecard '{alert.get('change_type')}' Incident"
                incident["occurred"] = \
                    datetime.strptime(alert_created_at, SECURITYSCORECARD_DATE_FORMAT).strftime(DATE_FORMAT)
                incident["rawJSON"] = json.dumps(alert)
                incidents_to_import.append(incident)
    # If there are no alerts then we can't use the most recent alert timestamp
    # So we'll use now as the last run timestamp
    else:
        now = int(datetime.utcnow().timestamp())
        demisto.debug(f"No alerts retrieved, setting last_run to now ({now})")
        demisto.setLastRun({
            'last_run': now
        })

    return incidents_to_import


""" COMMAND FUNCTIONS """


def test_module(client: Client) -> str:
    """Tests API connectivity and authentication

    Runs the fetch-alerts mechanism to validate all integration parameters

    :type client: ``Client``
    :param Client: client to use

    :return: 'ok' if test passed, anything else will fail the test.
    :rtype: ``str``
    """

    username_input = params.get('username').get("identifier")  # type: ignore

    message: str = ''
    try:
        client.fetch_alerts(
            username=username_input,
            page_size=1)
        message = 'ok'
    except DemistoException as e:
        if 'Unauthorized' in str(e):
            message = 'Authorization Error: make sure API Key is correctly set'
        else:
            raise e
    return message

# region Methods
# ---------------


def securityscorecard_portfolios_list_command(client: Client) -> CommandResults:
    """`securityscorecard_portfolios_list_command`: List all Portfolios you have access to.

    See https://securityscorecard.readme.io/reference#get_portfolios

    :type ``client``: ``Client``

    :return:
        A ``CommandResults`` object that is passed to ``return_results``
    :rtype: ``CommandResults``
    """

    portfolios = client.get_portfolios()

    # For mypy
    # error: Argument 1 to "int" has incompatible type "Optional[Any]";
    # expected "Union[str, bytes, SupportsInt, _SupportsIndex]"
    portfolios_total = portfolios.get("total")
    assert portfolios_total is not None
    portfolios_count = int(portfolios_total)

    # Check that API returned more than 0 portfolios
    if portfolios_count == 0:
        return_warning("No Portfolios were found in your account. Please create a new one and try again.", exit=True)

    # API response is a dict with 'entries'
    entries = portfolios.get('entries')

    markdown = tableToMarkdown('Your SecurityScorecard Portfolios', entries, headers=['id', 'name', 'privacy'])

    results = CommandResults(
        readable_output=markdown,
        outputs_prefix='SecurityScorecard.Portfolio',
        outputs_key_field='id',
        outputs=portfolios
    )

    return results


def securityscorecard_portfolio_list_companies_command(client: Client, args: Dict[str, Any]) -> CommandResults:
    """`securityscorecard_portfolio_list_companies_command`: Retrieve all companies in portfolio.

    https://securityscorecard.readme.io/reference#get_portfolios-portfolio-id-companies

    :type ``client``: ``Client``
    :type `` args``: ``Dict[str, Any]``
        ``args['portfolio_id']``: Portfolio ID.
            A list of Portfolio IDs can be retrieved using the `!securityscorecard-portfolios-list` command., type ``String``
        ``args['grade']``: Grade filter. The acceptable values are capitalized letters between A-F, e.g. B., type ``String``
        ``args['industry']``: Industry filter.
            The acceptable values are capitalized, e.g. INFORMATION_SERVICES, TECHNOLOGY., type ``String``
        ``args['vulnerability']``: Vulnerability filter, type ``String``
        ``args['issue_type']``: Issue type filter, type ``String``
        ``args['had_breach_within_last_days']``:
            Domains with breaches in the last X days. Possible values are numbers, e.g. 1000., type ``Number``

    :return:
        A ``CommandResults`` object that is passed to ``return_results``
    :rtype: ``CommandResults``
    """

    demisto.debug(f"securityscorecard_portfolio_list_companies_command called with args: {args}")

    portfolio_id = str(args.get('portfolio_id'))

    # Validate grade argument
    if 'grade' in args:
        grade = args.get('grade')
    else:
        grade = None

    # Validate and transform industry
    # We need to capitalize the industry to conform to API
    industry = None
    if 'industry' in args:
        industry_arg = str(args.get('industry'))
        industry = str.upper(industry_arg)
    # else:
    #     industry = None

    vulnerability = args.get('vulnerability')

    issue_type = args.get('issue_type')

    had_breach_within_last_days = arg_to_number(
        arg=args.get('had_breach_within_last_days'),
        arg_name='had_breach_within_last_days',
        required=False
    )

    response = client.get_companies_in_portfolio(
        portfolio=portfolio_id,
        grade=grade,
        industry=industry,
        vulnerability=vulnerability,
        issue_type=issue_type,
        had_breach_within_last_days=had_breach_within_last_days
    )

    # Check if the portfolio has more than 1 company
    # Throw warning to UI if there are no companies
    # str cast for mypy type incompatiblity
    total_portfolios = int(str(response.get('total')))

    if not total_portfolios > 0:
        return_warning(f"No companies found in Portfolio {portfolio_id}. Please add a company to it and retry.")

    companies = response.get('entries')

    title = f"**{total_portfolios}** companies found in Portfolio {portfolio_id}\n"
    markdown = tableToMarkdown(
        title,
        companies,
        headers=['domain', 'name', 'score', 'last30days_score_change', 'industry', 'size']
    )

    results = CommandResults(
        "SecurityScorecard.Company",
        readable_output=markdown,
        outputs=companies
    )

    return results


def securityscorecard_company_score_get_command(client: Client, args: Dict[str, Any]) -> CommandResults:
    """securityscorecard_company_score_get_command: Retrieve company overall score.

    See https://securityscorecard.readme.io/reference#get_companies-scorecard-identifier-factors

    :type ``client``: ``Client``
    :type `` args``: ``Dict[str, Any]``
        ``args['domain']``: Company domain, e.g. google.com, type ``String``

    :return:
        A ``CommandResults`` object that is passed to ``return_results``
    :rtype: ``CommandResults``
    """

    # str cast for mypy compatibility
    domain = str(args.get('domain'))

    score = client.get_company_score(domain=domain)
    score["domain"] = f"[{domain}](https://{domain})"

    industry = str(score.get("industry")).title().replace("_", " ")
    score["industry"] = industry

    markdown = tableToMarkdown(
        f"Domain {domain} Scorecard",
        score,
        headers=['name', 'domain', 'grade', 'score', 'industry', 'last30day_score_change', 'size']
    )

    results = CommandResults(
        readable_output=markdown,
        outputs_prefix="SecurityScorecard.Company.Score",
        outputs=score
    )

    return results


def securityscorecard_company_factor_score_get_command(client: Client, args: Dict[str, Any]) -> CommandResults:
    """`securityscorecard_company_factor_score_get_command`: Retrieve company factor score and scores

    See https://securityscorecard.readme.io/reference#get_companies-scorecard-identifier-factors

    :type ``client``: ``Client``
    :type `` args``: ``Dict[str, Any]``
        ``args['domain']``: Company domain., type ``String``
        ``args['severity_in']``: Issue severity filter.
        Optional values can be positive, info, low, medium, high.
        Can be comma-separated list, e.g. 'medium,high,positive', type ``array``

    :return:
        A ``CommandResults`` object that is passed to ``return_results``
    :rtype: ``CommandResults``
    """

    domain = str(args.get('domain'))

    severity_in = args.get('severity_in')

    response = client.get_company_factor_score(domain, severity_in)

    demisto.debug(f"factor score response: {response}")
    entries = response['entries']

    factor_scores = []
    for entry in entries:
        score = {}
        score["Name"] = entry.get("name").title().replace("_", " ")
        score["Grade"] = entry.get("grade")
        score["Score"] = entry.get("score")
        score["Issues"] = len(entry.get("issue_summary"))
        score["Issue Details"] = entry.get("issue_summary")
        factor_scores.append(score)

    markdown = tableToMarkdown(
        f"Domain [{domain}](https://{domain}) Scorecard",
        factor_scores,
        headers=['Name', 'Grade', 'Score', 'Issues']
    )

    results = CommandResults(
        readable_output=markdown,
        outputs_prefix="SecurityScorecard.Company.Factor",
        outputs=factor_scores
    )

    return results


def securityscorecard_company_history_score_get_command(client: Client, args: Dict[str, Any]) -> CommandResults:

    """securityscorecard_company_history_score_get_command: Retrieve company historical scores

    See https://securityscorecard.readme.io/reference#get_companies-scorecard-identifier-history-score

    :type ``client``: ``Client``
    :type `` args``: ``Dict[str, Any]``
        ``args['domain']``: Company domain, e.g. google.com, type ``String``.
        ``args['from']``: Initial date for historical data. Value should be in format `YYYY-MM-DD`, type ``Date``.
        ``args['to']``: Initial date for historical data. Value should be in format `YYYY-MM-DD`, type ``Date``.
            By default, if `from` and `to` are not supplied, the API will return 1 year back.
        ``args['timing']``: Timing granularity. Acceptable values are `weekly` or `daily`, type ``String``, Default: `daily`.

    :return:
        A ``CommandResults`` object that is passed to ``return_results``
    :rtype: ``CommandResults``
    """

    domain = str(args.get('domain'))

    _from = args.get('from')
    to = args.get('to')
    timing = str(args.get('timing'))

    response = client.get_company_historical_scores(domain=domain, _from=_from, to=to, timing=timing)  # type: ignore

    entries = response.get('entries')

    markdown = tableToMarkdown(
        f"Historical Scores for Domain [`{domain}`](https://{domain})",
        entries,
        headers=['date', 'score']
    )

    results = CommandResults(
        readable_output=markdown,
        outputs_prefix="SecurityScorecard.Company.History",
        outputs=entries
    )

    return results


def securityscorecard_company_history_factor_score_get_command(client: Client, args: Dict[str, Any]) -> CommandResults:

    """`securityscorecard_company_history_factor_score_get_command`: Retrieve company historical factor scores

    See https://securityscorecard.readme.io/reference#get_companies-scorecard-identifier-history-factors-score

    :type ``client``: ``Client``
    :type `` args``: ``Dict[str, Any]``
        ``args['domain']``: Company domain, e.g. google.com, type ``String``.
        ``args['from']``: Initial date for historical data. Value should be in format `YYYY-MM-DD`, type ``Date``.
        ``args['to']``: Initial date for historical data. Value should be in format `YYYY-MM-DD`, type ``Date``.
            By default, if `from` and `to` are not supplied, the API will return 1 year back.
        ``args['timing']``: Timing granularity.
        date granularity, it could be "daily" (default), "weekly" or "monthly", type ``String``, Default: `daily`.

    :return:
        A ``CommandResults`` object that is passed to ``return_results``
    :rtype: ``CommandResults``
    """

    domain = str(args.get('domain'))
    _from = args.get('from')
    to = args.get('to')
    timing = str(args.get('timing'))

    response = client.get_company_historical_factor_scores(domain=domain, _from=_from, to=to, timing=timing)  # type: ignore

    entries = response['entries']

    factor_scores = []

    for entry in entries:
        f = {}
        f["Date"] = entry.get("date").split("T")[0]

        factors = entry.get("factors")
        factor_row = ''
        for factor in factors:
            factor_name = factor.get("name").title().replace("_", " ")
            factor_score = factor.get("score")

            factor_row = factor_row + f"{factor_name}: {factor_score}\n"

        f["Factors"] = factor_row
        factor_scores.append(f)

    markdown = tableToMarkdown(f"Historical Factor Scores for Domain [`{domain}`](https://{domain})", factor_scores)

    results = CommandResults(
        readable_output=markdown,
        outputs_prefix="SecurityScorecard.Company.FactorHistory",
        outputs=entries
    )

    return results


def securityscorecard_alert_grade_change_create_command(client: Client, args: Dict[str, Any]) -> CommandResults:

    """securityscorecard_alert_grade_change_create_command: Create alert based on grade

    See https://securityscorecard.readme.io/reference#post_users-by-username-username-alerts-grade

    :type ``client``: ``Client``
    :type `` args``: ``Dict[str, Any]``
        ``args['change_direction']``: Direction of change. Possible values are 'rises' or 'drops'., type ``String``
        ``args['score_types']``: Types of risk factors to monitor.
        Possible values are:
        'overall',
        'any_factor_score',
        'network_security',
        'dns_health',
        'patching_cadence',
        'endpoint_security',
        'ip_reputation',
        'application_security',
        'cubit_score',
        'hacker_chatter',
        'leaked_information',
        'social_engineering'. For multiple factors, ['leaked_information', 'social_engineering'], type ``array``
        `args['target']``: What do you want to monitor with this alert.
        It could be one of the following 'my_scorecard', 'any_followed_company', or an array of portfolio IDs,
        e.g. xxxxxxxxxxxxxxxxxxxxxx,yyyyyyyyyyyyyyyyyyyyy, type ``array``

    :return:
        A ``CommandResults`` object that is passed to ``return_results``
    :rtype: ``CommandResults``
    """

    email = params.get('username').get("identifier")  # type: ignore
    change_direction = str(args.get('change_direction'))
    score_types = argToList(args.get('score_types'))
    target = argToList(args.get('target'))

    demisto.debug(f"Attempting to create alert with body {args}")
    response = client.create_grade_change_alert(
        email=email,
        change_direction=change_direction,
        score_types=score_types,
        target=target
    )
    demisto.debug(f"Response received: {response}")
    alert_id = response.get("id")

    markdown = f"Alert **{alert_id}** created"

    results = CommandResults(
        readable_output=markdown,
        outputs_prefix="SecurityScorecard.GradeChangeAlert.id",
        outputs=alert_id
    )

    return results


def securityscorecard_alert_score_threshold_create_command(client: Client, args: Dict[str, Any]) -> CommandResults:

    """securityscorecard_alert_score_threshold_create_command: Create alert based threshold met

    :type ``client``: ``Client``
    :type `` args``: ``Dict[str, Any]``
        ``args['change_direction']``: Direction of change. Possible values are 'rises_above' or 'drops_below'., type ``String``
        ``args['threshold']``: The numeric score used as the threshold to trigger the alert, type ``Number``
        ``args['score_types']``: Types of risk factors to monitor.
        Possible values are:
        'overall',
        'any_factor_score',
        'network_security',
        'dns_health',
        'patching_cadence',
        'endpoint_security',
        'ip_reputation',
        'application_security',
        'cubit_score',
        'hacker_chatter',
        'leaked_information',
        'social_engineering'. For multiple factors, ['leaked_information', 'social_engineering'], type ``array``
        ``args['target']``: What do you want to monitor with this alert.
        It could be one of the following 'my_scorecard', 'any_followed_company', type ``str``
        ``args['portfolios']``: A comma-separated list of Portfolios
        (i.e. xxxxxxxxxxxxxxxxxxxxxxxxx,yyyyyyyyyyyyyyyyyyyyy) to monitor with the alert.
        The alert will be triggered once any one of the companies within the specified Portfolio
        meets the set threshold This argument is require if the `target` argument is not specified.

    :return:
        A ``CommandResults`` object that is passed to ``return_results``
    :rtype: ``CommandResults``
    """

    email = params.get('username').get("identifier")  # type: ignore
    change_direction = str(args.get('change_direction'))
    threshold = arg_to_number(args.get('threshold'))  # type: ignore
    score_types = argToList(args.get('score_types'))
    target_arg = argToList(args.get('target'))
    portfolios = argToList(args.get('portfolios'))

    # Only one argument between portfolios and target should be defined
    # Return error if neither of them is defined or if both are defined
    # Else choose the one that is defined and use it as the target
    if portfolios and target_arg:
        raise DemistoException("Both 'portfolio' and 'target' argument have been set. \
        Please remove one of them and try again.")
    elif target_arg and not portfolios:
        target = target_arg
    elif portfolios and not target_arg:
        target = portfolios
    else:
        raise DemistoException("Either 'portfolio' or 'target' argument must be given")

    demisto.debug(f"Attempting to create alert with body {args}")
    response = client.create_score_threshold_alert(
        email=email,
        change_direction=change_direction,
        threshold=threshold,  # type: ignore
        score_types=score_types,
        target=target
    )
    demisto.debug(f"Response received: {response}")
    alert_id = response.get("id")

    markdown = f"Alert **{alert_id}** created"

    results = CommandResults(
        readable_output=markdown,
        outputs_prefix="SecurityScorecard.ScoreThresholdAlert.id",
        outputs=alert_id
    )

    return results


def securityscorecard_alert_delete_command(client: Client, args: Dict[str, Any]) -> CommandResults:

    """`securityscorecard_alert_delete_command`: Delete an alert
    See https://securityscorecard.readme.io/reference#delete_users-by-username-username-alerts-grade-alert

    :type ``client``: ``Client``
    :type `` args``: ``Dict[str, Any]``
        ``args['alert_id']``: Alert ID, type ``String``
        ``args['alert_type']``: Alert type. Can be either `score` or `grade`, type ``String``

    :return:
        A ``CommandResults`` object that is passed to ``return_results``
    :rtype: ``CommandResults``
    """

    email = params.get('username').get("identifier")  # type: ignore
    alert_id = str(args.get("alert_id"))
    alert_type = str(args.get("alert_type"))
    client.delete_alert(email=email, alert_id=alert_id, alert_type=alert_type)

    markdown = f"{str.capitalize(alert_type)} alert **{alert_id}** deleted"

    results = CommandResults(readable_output=markdown)

    return results


def securityscorecard_alerts_list_command(client: Client, args: Dict[str, Any]) -> CommandResults:

    """`securityscorecard_alerts_list_command`: Retrieve alerts triggered in the last week

    See https://securityscorecard.readme.io/reference#get_users-by-username-username-notifications-recent

    :type ``client``: ``Client``
    :type `` args``: ``Dict[str, Any]``
        ``args['portfolio_id']``: Portfolio ID. Can be retrieved using `!securityscorecard-portfolios-list`, type ``String``

    :return:
        A ``CommandResults`` object that is passed to ``return_results``
    :rtype: ``CommandResults``
    """

    email = params.get('username').get("identifier")  # type: ignore
    demisto.debug(f"email: {email}")
    portfolio_id = args.get('portfolio_id')

    demisto.debug(f"Sending request to retrieve alerts with arguments {args}")

    response = client.get_alerts_last_week(email=email, portfolio_id=portfolio_id)

    entries = response["entries"]

    # Retrieve the alert metadata (direction, score, factor, grade_letter, score_impact)
    alerts = []

    for entry in entries:
        # change_data is a list that includes all alert metadata that triggered the event
        changes = entry.get("change_data")
        for change in changes:
            alert = {}
            alert["id"] = entry.get("id")
            alert["change_type"] = entry.get("change_type")
            alert["domain"] = entry.get("domain")
            alert["company"] = entry.get("company_name")
            alert["created"] = entry.get("created_at")
            alert["direction"] = change.get("direction")
            alert["score"] = change.get("score")
            alert["factor"] = change.get("factor")
            alert["grade_letter"] = change.get("grade_letter")
            alert["score_impact"] = change.get("score_impact")
            alerts.append(alert)

    markdown = tableToMarkdown(f"Latest Alerts for user {email}", alerts)

    results = CommandResults(
        outputs_prefix="SecurityScorecard.Alert",
        outputs_key_field="id",
        readable_output=markdown,
        outputs=alerts
    )

    return results


def securityscorecard_company_services_get_command(client: Client, args: Dict[str, Any]) -> CommandResults:

    """securityscorecard_company_services_get_command: Retrieve the service providers of a domain

    See https://securityscorecard.readme.io/reference#get_companies-domain-services

    :type ``client``: ``Client``
    :type `` args``: ``Dict[str, Any]``
        ``args['domain']``: Company domain, type ``String``

    :return:
        A ``CommandResults`` object that is passed to ``return_results``
    :rtype: ``CommandResults``
    """

    domain = str(args.get("domain"))
    response = client.get_domain_services(domain=domain)

    entries = response["entries"]

    services = []

    for entry in entries:
        categories = entry.get("categories")
        for category in categories:
            service = {}
            service["vendor_domain"] = entry.get("vendor_domain")
            service["category"] = category
            services.append(service)

    markdown = tableToMarkdown(f"Services for domain [{domain}](https://{domain})", services)

    results = CommandResults(
        outputs_prefix="SecurityScorecard.Company.Service",
        outputs=entries,
        readable_output=markdown
    )

    return results


def fetch_alerts(client: Client, params: Dict):

    """
    Fetch incidents/alerts from SecurityScorecard API

    See https://securityscorecard.readme.io/reference#get_users-by-username-username-notifications-recent

    The API is updated on a daily basis therefore `incidentFetchInterval` is set to 1440 (minutes per day)
    The API returns all alerts received in the last week.

    Every alert has a `"created_at"` parameter to notify when the alert was triggered.
    This method will create incidents only for alerts that occurred on the day the alert was created.

    :return:
        ``None``
    :rtype: ``None``
    """
    # Set the query size

    if not params.get("max_fetch"):
        max_incidents = 50
    else:
        max_incidents = arg_to_number(params.get("max_fetch"))  # type: ignore

    # User/email to fetch alerts for
    username = params.get('username').get("identifier")  # type: ignore

    results = client.fetch_alerts(page_size=max_incidents, username=username)

    alerts = results.get("entries")

    demisto.debug(f"API returned {str(len(alerts))} alerts")

    # Check if the API returned any alerts
    if len(alerts) > 0:
        incidents = incidents_to_import(alerts=alerts)

        # Check if any incidents should be imported according to last run time timestamp
        if len(incidents) > 0:
            demisto.debug(f"{str(len(incidents))} Incidents will be imported")
            demisto.debug(f"Incidents: {incidents}")
            demisto.incidents(incidents)
        else:
            demisto.debug("No incidents will be imported.")
            demisto.incidents([])
    # Return no incidents if API returned no alerts
    else:
        demisto.debug("API returned no alerts. Returning empty incident list")
        demisto.incidents([])


""" MAIN FUNCTION """


def main() -> None:
    """main function, parses params and runs command functions
    """

    global params
    params = demisto.params()  # type: ignore

    api_key = params.get('username').get("password")  # type: ignore

    # SecurityScorecard API URL
    base_url = params.get('base_url', "https://api.securityscorecard.io/")  # type: ignore

    # Default configuration
    verify_certificate = not params.get('insecure', False)  # type: ignore
    proxy = params.get('proxy', False)  # type: ignore

    demisto.debug(f'Command being called is {demisto.command()}')
    try:

        headers: Dict = {"Authorization": f"Token {api_key}"}

        client = Client(
            base_url=base_url,
            verify=verify_certificate,
            headers=headers,
            proxy=proxy)

        if demisto.command() == 'test-module':
            # This is the call made when pressing the integration Test button.
            result = test_module(client)
            return_results(result)
        elif demisto.command() == "fetch-incidents":
            fetch_alerts(client, params)  # type: ignore
        elif demisto.command() == 'securityscorecard-portfolios-list':
            return_results(securityscorecard_portfolios_list_command(client))
        elif demisto.command() == 'securityscorecard-portfolio-list-companies':
            return_results(securityscorecard_portfolio_list_companies_command(client, demisto.args()))
        elif demisto.command() == 'securityscorecard-company-score-get':
            return_results(securityscorecard_company_score_get_command(client, demisto.args()))
        elif demisto.command() == 'securityscorecard-company-factor-score-get':
            return_results(securityscorecard_company_factor_score_get_command(client, demisto.args()))
        elif demisto.command() == 'securityscorecard-company-history-score-get':
            return_results(securityscorecard_company_history_score_get_command(client, demisto.args()))
        elif demisto.command() == 'securityscorecard-company-history-factor-score-get':
            return_results(securityscorecard_company_history_factor_score_get_command(client, demisto.args()))
        elif demisto.command() == 'securityscorecard-alert-grade-change-create':
            return_results(securityscorecard_alert_grade_change_create_command(client, demisto.args()))
        elif demisto.command() == 'securityscorecard-alert-score-threshold-create':
            return_results(securityscorecard_alert_score_threshold_create_command(client, demisto.args()))
        elif demisto.command() == 'securityscorecard-alert-delete':
            return_results(securityscorecard_alert_delete_command(client, demisto.args()))
        elif demisto.command() == 'securityscorecard-alerts-list':
            return_results(securityscorecard_alerts_list_command(client, demisto.args()))
        elif demisto.command() == 'securityscorecard-company-services-get':
            return_results(securityscorecard_company_services_get_command(client, demisto.args()))

    # Log exceptions and return errors
    except Exception as e:
        demisto.error(traceback.format_exc())  # print the traceback
        return_error(f'Failed to execute {demisto.command()} command.\nError:\n{str(e)}')


""" ENTRY POINT """

if __name__ in ('__main__', '__builtin__', 'builtins'):
    main()