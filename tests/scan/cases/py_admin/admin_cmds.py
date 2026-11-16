from django import forms
from django.contrib import admin
from django.core.management.base import BaseCommand


def validate_email(value):
    if "\n" in value:
        raise forms.ValidationError("Email address must not contain line breaks.")


class EmailAdmin(admin.ModelAdmin):
    @admin.action(description="Requeue selected emails")
    def requeue(self, request, queryset):
        queryset.update(status=2)


class Command(BaseCommand):
    help = "Delete orphaned attachments."

    def add_arguments(self, parser):
        parser.add_argument("-l", "--lockfile", type=str, help="Absolute path of lockfile to acquire")
