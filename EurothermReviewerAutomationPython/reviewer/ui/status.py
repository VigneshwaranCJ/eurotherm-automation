"""Native database and indexing readiness."""
from ..common.errors import WorkflowError


def reviewer_status(page):
    return page.evaluate("""() => new Promise((resolve,reject) => {
        const timer=setTimeout(()=>reject(new Error('Reviewer status timed out')),30000);
        window.angular.element(document.body).injector().get('databaseService').getStats(
            r=>{clearTimeout(timer);resolve(r.data);},
            ()=>{clearTimeout(timer);reject(new Error('Reviewer database status unavailable'));});
    })""")


def assert_reviewer_ready(status):
    if not status.get("indexingEnable"):
        raise WorkflowError("INDEXING_DISABLED", f"Reviewer indexing is disabled: {status}")
