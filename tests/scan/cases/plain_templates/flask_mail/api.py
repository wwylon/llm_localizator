class WebServiceError(Exception):
    def __init__(self, code="", desc=None, status=400):
        super().__init__()
        self.code, self.desc, self.status = code, desc, status


class AccessDenied(WebServiceError):
    def __init__(self):
        super().__init__(code="access_denied", desc="Access to the requested resource has been denied", status=403)


def vote(review, user):
    if review.user_id == user.id:
        raise InvalidRequest(desc="You cannot rate your own review.")
    if user.over_limit:
        raise LimitExceeded("You have exceeded your limit of votes per day.")
    if review.spam:
        raise InvalidRequest("own")
