from rest_framework.routers import DefaultRouter

from .views import (
    EmployeeRiskSnapshotViewSet,
    InterventionViewSet,
    RiskExplanationViewSet,
    RiskPredictionViewSet,
    WellbeingViewSet,
)

router = DefaultRouter()
router.register("risk-snapshots", EmployeeRiskSnapshotViewSet, basename="risk-snapshot")
router.register("risk-predictions", RiskPredictionViewSet, basename="risk-prediction")
router.register("risk-explanations", RiskExplanationViewSet, basename="risk-explanation")
router.register("interventions", InterventionViewSet, basename="intervention")
router.register("wellbeing", WellbeingViewSet, basename="wellbeing")

urlpatterns = router.urls
