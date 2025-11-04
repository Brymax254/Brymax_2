#!/usr/bin/env python
"""
Automated Migration Script: Cloudinary to Local Storage
This script will:
1. Update models.py to replace CloudinaryField with ImageField
2. Update serializers.py in api/ subdirectory to handle local images
3. Update settings.py for media configuration
4. Update urls.py to serve media files
5. Create admin.py configuration
6. Create forms.py configuration
7. Migrate existing images from Cloudinary to local storage
8. Update frontend JavaScript
"""

import os
import re
import sys
import shutil
import requests
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.files import File
from django.db import models
from django.apps import apps
from io import BytesIO
from PIL import Image

# Configuration
PROJECT_ROOT = Path(__file__).resolve().parent
BOOKINGS_APP = PROJECT_ROOT / 'bookings'
BOOKINGS_API = BOOKINGS_APP / 'api'
MEDIA_ROOT = PROJECT_ROOT / 'media'
VEHICLES_MEDIA_DIR = MEDIA_ROOT / 'vehicles'

# Ensure media directory exists
VEHICLES_MEDIA_DIR.mkdir(parents=True, exist_ok=True)


def backup_file(file_path):
    """Create a backup of a file before modifying it."""
    backup_path = f"{file_path}.backup"
    if os.path.exists(file_path):
        shutil.copy2(file_path, backup_path)
        print(f"Created backup: {backup_path}")
    return backup_path


def ensure_file_exists(file_path, initial_content=""):
    """Ensure a file exists, create it if it doesn't."""
    if not os.path.exists(file_path):
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w') as f:
            f.write(initial_content)
        print(f"Created missing file: {file_path}")


def update_models_py():
    """Update models.py to replace CloudinaryField with ImageField."""
    models_file = BOOKINGS_APP / 'models.py'
    backup_file(models_file)

    with open(models_file, 'r') as f:
        content = f.read()

    # Remove Cloudinary imports
    content = re.sub(r'from cloudinary\.models import CloudinaryField\n', '', content)

    # Replace CloudinaryField with ImageField
    content = re.sub(
        r'image = CloudinaryField\(\s*["\']vehicle_image["\'],\s*folder=[\'"]vehicles[\'"],\s*blank=True,\s*null=True,\s*help_text=["\']Upload main vehicle image["\']\s*\)',
        '''image = models.ImageField(
        upload_to='vehicles/%Y/%m/',
        blank=True,
        null=True,
        validators=[validate_image_file_extension],
        help_text="Upload main vehicle image (max 5MB)"
    )''',
        content,
        flags=re.MULTILINE | re.DOTALL
    )

    # Add validation function if not present
    if 'def validate_image_file_extension' not in content:
        # Find the imports section
        import_end = content.find('# =============================================================================')
        if import_end == -1:
            import_end = content.find('import')

        # Add validation function after imports
        validation_func = '''
# =============================================================================
# IMAGE VALIDATION
# =============================================================================

def validate_image_file_extension(value):
    """
    Validate that the uploaded file has a valid image extension.
    """
    import os
    from django.core.exceptions import ValidationError

    ext = os.path.splitext(value.name)[1]
    valid_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp']
    if not ext.lower() in valid_extensions:
        raise ValidationError('Unsupported file extension. Allowed extensions are: %s.' % ', '.join(valid_extensions))

'''
        content = content[:import_end] + validation_func + content[import_end:]

    # Update image_url property
    content = re.sub(
        r'@property\s+def image_url\(self\):\s+"""Return the URL of the vehicle image \(Cloudinary → external → default\)."""\s+if self\.external_image_url:\s+return self\.external_image_url\s+if self\.image:\s+try:\s+return self\.image\.url\s+except Exception:\s+pass\s+return self\.get_default_image_url\(\)',
        '''@property
    def image_url(self):
        """Return the URL of the vehicle image (local → external → default)."""
        if self.image:
            return self.image.url
        elif self.external_image_url:
            return self.external_image_url
        return self.get_default_image_url()''',
        content,
        flags=re.MULTILINE | re.DOTALL
    )

    # Update clean method to validate image size
    clean_method = re.search(r'def clean\(self\):.*?(?=\n    def|\nclass|\Z)', content, re.MULTILINE | re.DOTALL)
    if clean_method:
        clean_content = clean_method.group(0)
        if 'image.size' not in clean_content:
            # Add image size validation
            new_clean = clean_content.replace(
                'super().clean()',
                '''super().clean()

        # Validate image size
        if self.image and self.image.size > 5 * 1024 * 1024:  # 5MB limit
            raise ValidationError({
                "image": "Image file size cannot exceed 5MB."
            })'''
            )
            content = content.replace(clean_content, new_clean)

    with open(models_file, 'w') as f:
        f.write(content)

    print("Updated models.py")


def update_serializers_py():
    """Update/create serializers.py in api/ subdirectory to handle local images."""
    serializers_file = BOOKINGS_API / 'serializers.py'

    # Ensure the file exists
    ensure_file_exists(serializers_file, '''# =============================================================================
# IMPORTS
# =============================================================================
from rest_framework import serializers
from bookings.models import Vehicle

''')

    backup_file(serializers_file)

    with open(serializers_file, 'r') as f:
        content = f.read()

    # Check if VehicleSerializer already exists
    if 'class VehicleSerializer(serializers.ModelSerializer):' in content:
        # Replace the existing VehicleSerializer
        serializer_pattern = r'class VehicleSerializer\(serializers\.ModelSerializer\):.*?(?=\n\nclass|\n# =============================================================================|\Z)'
        new_serializer = '''class VehicleSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    image = serializers.ImageField(required=False, allow_null=True)

    class Meta:
        model = Vehicle
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')

    def get_image_url(self, obj):
        """Return the full URL of the vehicle image."""
        request = self.context.get('request')
        if obj.image:
            # Build absolute URL if request is available
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        elif obj.external_image_url:
            return obj.external_image_url
        return obj.get_default_image_url()

    def validate_image(self, value):
        """Validate image file."""
        if value:
            # Check file size
            if value.size > 5 * 1024 * 1024:
                raise serializers.ValidationError("Image file size cannot exceed 5MB.")

            # Check file extension
            import os
            allowed_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp']
            file_extension = os.path.splitext(value.name)[1].lower()
            if file_extension not in allowed_extensions:
                raise serializers.ValidationError(
                    f"Unsupported image format. Allowed formats: {', '.join(allowed_extensions)}"
                )
        return value'''

        content = re.sub(serializer_pattern, new_serializer, content, flags=re.MULTILINE | re.DOTALL)
    else:
        # Add the VehicleSerializer at the end
        new_serializer = '''

# =============================================================================
# VEHICLE SERIALIZER
# =============================================================================

class VehicleSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    image = serializers.ImageField(required=False, allow_null=True)

    class Meta:
        model = Vehicle
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')

    def get_image_url(self, obj):
        """Return the full URL of the vehicle image."""
        request = self.context.get('request')
        if obj.image:
            # Build absolute URL if request is available
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        elif obj.external_image_url:
            return obj.external_image_url
        return obj.get_default_image_url()

    def validate_image(self, value):
        """Validate image file."""
        if value:
            # Check file size
            if value.size > 5 * 1024 * 1024:
                raise serializers.ValidationError("Image file size cannot exceed 5MB.")

            # Check file extension
            import os
            allowed_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp']
            file_extension = os.path.splitext(value.name)[1].lower()
            if file_extension not in allowed_extensions:
                raise serializers.ValidationError(
                    f"Unsupported image format. Allowed formats: {', '.join(allowed_extensions)}"
                )
        return value
'''
        content += new_serializer

    with open(serializers_file, 'w') as f:
        f.write(content)

    print("Updated serializers.py")


def update_settings_py():
    """Update settings.py for media configuration."""
    settings_file = PROJECT_ROOT / 'settings.py'
    backup_file(settings_file)

    with open(settings_file, 'r') as f:
        content = f.read()

    # Add media settings if not present
    if 'MEDIA_URL' not in content:
        # Find a good place to add the media settings (after STATIC_URL)
        static_url_match = re.search(r'STATIC_URL = [\'"]\/static\/[\'"]', content)
        if static_url_match:
            insert_pos = static_url_match.end()

            media_settings = '''

# Media files configuration
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# File upload settings
FILE_UPLOAD_MAX_MEMORY_SIZE = 5242880  # 5MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 5242880  # 5MB

# Allowed upload extensions
ALLOWED_UPLOAD_IMAGES = ['.jpg', '.jpeg', '.png', '.gif', '.webp']'''

            content = content[:insert_pos] + media_settings + content[insert_pos:]

    with open(settings_file, 'w') as f:
        f.write(content)

    print("Updated settings.py")


def update_urls_py():
    """Update urls.py to serve media files."""
    urls_file = PROJECT_ROOT / 'urls.py'
    backup_file(urls_file)

    with open(urls_file, 'r') as f:
        content = f.read()

    # Add media URL pattern if not present
    if 'static(settings.MEDIA_URL' not in content:
        # Find the end of the urlpatterns list
        urlpatterns_end = content.find('urlpatterns = [')
        if urlpatterns_end != -1:
            # Find the closing bracket
            bracket_count = 0
            pos = urlpatterns_end + len('urlpatterns = [')
            for i, char in enumerate(content[pos:], pos):
                if char == '[':
                    bracket_count += 1
                elif char == ']':
                    bracket_count -= 1
                    if bracket_count == 0:
                        insert_pos = i + 1
                        break

            media_urls = '''

# Serve media files during development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)'''

            content = content[:insert_pos] + media_urls + content[insert_pos:]

    with open(urls_file, 'w') as f:
        f.write(content)

    print("Updated urls.py")


def create_admin_py():
    """Create or update admin.py for vehicle image handling."""
    admin_file = BOOKINGS_APP / 'admin.py'
    backup_file(admin_file)

    admin_content = '''from django.contrib import admin
from django.utils.html import format_html
from .models import Vehicle

@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ('make', 'model', 'year', 'license_plate', 'vehicle_type', 'is_active', 'image_preview')
    list_filter = ('vehicle_type', 'fuel_type', 'is_active')
    search_fields = ('make', 'model', 'license_plate')
    readonly_fields = ('image_preview', 'created_at', 'updated_at')

    fieldsets = (
        ('Basic Information', {
            'fields': ('make', 'model', 'year', 'color', 'license_plate', 'vehicle_type', 'fuel_type', 'capacity')
        }),
        ('Images', {
            'fields': ('image', 'external_image_url', 'image_preview')
        }),
        ('Documents', {
            'fields': ('logbook_copy', 'insurance_copy', 'inspection_certificate')
        }),
        ('Status', {
            'fields': ('is_active', 'insurance_expiry', 'inspection_expiry')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )

    def image_preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" width="150" height="100" style="object-fit: cover;" />', obj.image.url)
        elif obj.external_image_url:
            return format_html('<img src="{}" width="150" height="100" style="object-fit: cover;" />', obj.external_image_url)
        return "No image"
    image_preview.short_description = 'Image Preview'
'''

    with open(admin_file, 'w') as f:
        f.write(admin_content)

    print("Created/Updated admin.py")


def create_forms_py():
    """Create forms.py for vehicle form handling."""
    forms_file = BOOKINGS_APP / 'forms.py'
    backup_file(forms_file)

    forms_content = '''from django import forms
from django.core.exceptions import ValidationError
from .models import Vehicle

class VehicleForm(forms.ModelForm):
    class Meta:
        model = Vehicle
        fields = '__all__'
        widgets = {
            'image': forms.FileInput(attrs={'accept': 'image/*'}),
        }

    def clean_image(self):
        image = self.cleaned_data.get('image')
        if image:
            # Check file size
            if image.size > 5 * 1024 * 1024:
                raise forms.ValidationError("Image file size cannot exceed 5MB.")

            # Check file extension
            import os
            allowed_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp']
            file_extension = os.path.splitext(image.name)[1].lower()
            if file_extension not in allowed_extensions:
                raise forms.ValidationError(
                    f"Unsupported image format. Allowed formats: {', '.join(allowed_extensions)}"
                )
        return image
'''

    with open(forms_file, 'w') as f:
        f.write(forms_content)

    print("Created/Updated forms.py")


def migrate_images():
    """Migrate existing images from Cloudinary to local storage."""
    print("Starting image migration...")

    # Import here to avoid circular imports
    sys.path.append(str(PROJECT_ROOT))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings')

    import django
    django.setup()

    from bookings.models import Vehicle

    vehicles = Vehicle.objects.all()
    migrated_count = 0
    failed_count = 0

    for vehicle in vehicles:
        if hasattr(vehicle, 'image') and vehicle.image:
            try:
                # Check if it's a CloudinaryField
                if hasattr(vehicle.image, 'url') and 'cloudinary' in vehicle.image.url:
                    # Download image from Cloudinary
                    response = requests.get(vehicle.image.url, stream=True)
                    if response.status_code == 200:
                        # Generate local filename
                        filename = f"{vehicle.make}_{vehicle.model}_{vehicle.id}.jpg"
                        filepath = VEHICLES_MEDIA_DIR / filename

                        # Save image locally
                        with open(filepath, 'wb') as f:
                            for chunk in response.iter_content(1024):
                                f.write(chunk)

                        # Update vehicle record
                        with open(filepath, 'rb') as f:
                            vehicle.image.save(filename, File(f), save=True)

                        migrated_count += 1
                        print(f"Migrated image for {vehicle.make} {vehicle.model}")
                    else:
                        failed_count += 1
                        print(
                            f"Failed to download image for {vehicle.make} {vehicle.model}: HTTP {response.status_code}")
                else:
                    print(f"Skipping {vehicle.make} {vehicle.model} - not a Cloudinary image")
            except Exception as e:
                failed_count += 1
                print(f"Failed to migrate {vehicle.make} {vehicle.model}: {str(e)}")

    print(f"Migration complete: {migrated_count} images migrated, {failed_count} failed")


def update_frontend_js():
    """Update frontend JavaScript to handle local images."""
    # Find the HTML file with the JavaScript
    html_files = list(PROJECT_ROOT.glob('**/*.html'))
    target_file = None

    for html_file in html_files:
        with open(html_file, 'r') as f:
            content = f.read()
            if 'getVehicleImageUrl' in content:
                target_file = html_file
                break

    if not target_file:
        print("Could not find HTML file with JavaScript to update")
        return

    backup_file(target_file)

    with open(target_file, 'r') as f:
        content = f.read()

    # Update the getVehicleImageUrl function
    old_function = r'function getVehicleImageUrl\(vehicle\) \{.*?return imageUrl;\s*\}'
    new_function = '''function getVehicleImageUrl(vehicle) {
  // Default fallback image
  let imageUrl = getFallbackImage(vehicle.vehicle_type);

  // Try local image first
  if (vehicle.image_url) {
    imageUrl = vehicle.image_url;
  } else if (vehicle.external_image_url) {
    imageUrl = vehicle.external_image_url;
  } else if (vehicle.image) {
    // Handle direct image field if present
    if (typeof vehicle.image === 'string') {
      imageUrl = vehicle.image;
    } else if (vehicle.image.url) {
      imageUrl = vehicle.image.url;
    }
  }

  return imageUrl;
}'''

    content = re.sub(old_function, new_function, content, flags=re.MULTILINE | re.DOTALL)

    # Update the getVehicleImageUrl function
    old_function = r'function getVehicleImageUrl\(vehicle\) \{.*?return imageUrl;\s*\}'
    new_function = '''function getVehicleImageUrl(vehicle) {
  // Default fallback image
  let imageUrl = getFallbackImage(vehicle.vehicle_type);

  // Try local image first
  if (vehicle.image_url) {
    imageUrl = vehicle.image_url;
  } else if (vehicle.external_image_url) {
    imageUrl = vehicle.external_image_url;
  } else if (vehicle.image) {
    // Handle direct image field if present
    if (typeof vehicle.image === 'string') {
      imageUrl = vehicle.image;
    } else if (vehicle.image.url) {
      imageUrl = vehicle.image.url;
    }
  }

  return imageUrl;
}'''

    content = re.sub(old_function, new_function, content, flags=re.MULTILINE | re.DOTALL)

    # Update the image element creation
    old_img_creation = r'const img = el\([\'"]img[\'"], \{ classes: \[[\'"]vehicle-image[\'"]\], attrs: \{ alt:.*?\} \}\);'
    new_img_creation = '''const img = el('img', { 
      classes: ['vehicle-image'], 
      attrs: { 
        alt: `${vehicle.make || ''} ${vehicle.model || ''}`.trim(),
        src: getVehicleImageUrl(vehicle),
        loading: 'lazy'  // Add lazy loading for better performance
      } 
    });'''

    content = re.sub(old_img_creation, new_img_creation, content, flags=re.MULTILINE | re.DOTALL)

    with open(target_file, 'w') as f:
        f.write(content)

    print(f"Updated JavaScript in {target_file}")


def create_management_command():
    """Create a management command for future image migrations."""
    management_dir = BOOKINGS_APP / 'management' / 'commands'
    management_dir.mkdir(parents=True, exist_ok=True)

    # Create __init__.py files if they don't exist
    (BOOKINGS_APP / 'management' / '__init__.py').touch(exist_ok=True)
    (management_dir / '__init__.py').touch(exist_ok=True)

    command_file = management_dir / 'migrate_vehicle_images.py'
    command_content = '''from django.core.management.base import BaseCommand
from django.core.files import File
from django.conf import settings
import requests
import os
from bookings.models import Vehicle

class Command(BaseCommand):
    help = 'Migrate vehicle images from Cloudinary to local storage'

    def handle(self, *args, **options):
        vehicles = Vehicle.objects.all()

        for vehicle in vehicles:
            if vehicle.image and hasattr(vehicle.image, 'url'):
                try:
                    # Download image from Cloudinary
                    response = requests.get(vehicle.image.url, stream=True)
                    if response.status_code == 200:
                        # Generate local filename
                        filename = f"{vehicle.make}_{vehicle.model}_{vehicle.id}.jpg"
                        filepath = os.path.join(settings.MEDIA_ROOT, 'vehicles', filename)

                        # Save image locally
                        os.makedirs(os.path.dirname(filepath), exist_ok=True)
                        with open(filepath, 'wb') as f:
                            for chunk in response.iter_content(1024):
                                f.write(chunk)

                        # Update vehicle record
                        with open(filepath, 'rb') as f:
                            vehicle.image.save(filename, File(f), save=True)

                        self.stdout.write(
                            self.style.SUCCESS(f'Migrated image for {vehicle.make} {vehicle.model}')
                        )
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(f'Failed to migrate {vehicle.make} {vehicle.model}: {str(e)}')
                    )
'''

    with open(command_file, 'w') as f:
        f.write(command_content)

    print("Created management command for future migrations")


def create_image_optimization():
    """Create image optimization utilities."""
    utils_file = BOOKINGS_APP / 'utils.py'

    # Check if utils.py exists
    if not utils_file.exists():
        with open(utils_file, 'w') as f:
            f.write("# Utility functions for the bookings app\n")

    backup_file(utils_file)

    with open(utils_file, 'r') as f:
        content = f.read()

    # Add image optimization functions if not present
    if 'compress_vehicle_image' not in content:
        optimization_code = '''

# =============================================================================
# IMAGE OPTIMIZATION
# =============================================================================

from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.core.files import File
from PIL import Image
import io
from .models import Vehicle

@receiver(pre_save, sender=Vehicle)
def compress_vehicle_image(sender, instance, **kwargs):
    """Compress vehicle images before saving."""
    if instance.image and hasattr(instance.image, 'file'):
        img = Image.open(instance.image.file)

        # Convert to RGB if necessary
        if img.mode != 'RGB':
            img = img.convert('RGB')

        # Compress image
        output = io.BytesIO()
        img.save(output, format='JPEG', quality=85, optimize=True)
        output.seek(0)

        # Replace the original image with compressed version
        instance.image = File(output, name=instance.image.name)
'''

        with open(utils_file, 'w') as f:
            f.write(content + optimization_code)

    print("Added image optimization utilities")


def run_migrations():
    """Run Django migrations to update the database schema."""
    import subprocess
    try:
        subprocess.run([sys.executable, 'manage.py', 'makemigrations'], check=True)
        subprocess.run([sys.executable, 'manage.py', 'migrate'], check=True)
        print("Django migrations completed successfully")
    except subprocess.CalledProcessError as e:
        print(f"Error running migrations: {e}")


def main():
    """Main function to execute all migration steps."""
    print("Starting migration from Cloudinary to local storage...")

    # Update all the necessary files
    update_models_py()
    update_serializers_py()
    update_settings_py()
    update_urls_py()
    create_admin_py()
    create_forms_py()
    create_management_command()
    create_image_optimization()
    update_frontend_js()

    # Run Django migrations
    run_migrations()

    # Migrate existing images
    migrate_images()

    print("Migration completed successfully!")
    print("\nNext steps:")
    print("1. Test the admin interface to ensure images upload correctly")
    print("2. Test the frontend to ensure images display properly")
    print("3. For production, configure your web server to serve media files")
    print("4. Consider setting up a CDN for media files in production")


if __name__ == "__main__":
    main()