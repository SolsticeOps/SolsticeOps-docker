from django.db import models

class DockerRegistry(models.Model):
    """Model representing a Docker registry."""
    name = models.CharField(max_length=100)
    url = models.CharField(max_length=255, help_text="Registry URL (e.g., index.docker.io/v1/)")
    username = models.CharField(max_length=100, blank=True, null=True)
    password = models.CharField(max_length=255, blank=True, null=True, help_text="Password or API Token")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name
