"""Operations for gl-settings."""

from gl_settings.operations.approval_rule import ApprovalRuleOperation
from gl_settings.operations.base import Operation, get_operation_registry, register_operation
from gl_settings.operations.init_project import InitProjectOperation
from gl_settings.operations.merge_request_setting import MergeRequestSettingOperation
from gl_settings.operations.project_setting import ProjectSettingOperation

# Import all operations to register them
from gl_settings.operations.protect_branch import ProtectBranchOperation
from gl_settings.operations.protect_tag import ProtectTagOperation

__all__ = [
    "Operation",
    "register_operation",
    "get_operation_registry",
    "ProtectBranchOperation",
    "ProtectTagOperation",
    "ProjectSettingOperation",
    "ApprovalRuleOperation",
    "MergeRequestSettingOperation",
    "InitProjectOperation",
]
