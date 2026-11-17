from rest_framework.routers import DefaultRouter

from .views import EmployeeResponseViewSet, QuestionOptionViewSet, QuestionViewSet

router = DefaultRouter()
router.register("questions", QuestionViewSet, basename="question")
router.register("question-options", QuestionOptionViewSet, basename="question-option")
router.register("employee-responses", EmployeeResponseViewSet, basename="employee-response")

urlpatterns = router.urls
