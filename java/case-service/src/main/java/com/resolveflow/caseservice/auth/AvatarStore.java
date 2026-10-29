package com.resolveflow.caseservice.auth;

import com.resolveflow.caseservice.shopping.CommerceShoppingClient.Refused;
import java.awt.RenderingHints;
import java.awt.image.BufferedImage;
import java.io.ByteArrayInputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.UUID;
import javax.imageio.ImageIO;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

@Component
public class AvatarStore {
    private final Path root;

    public AvatarStore(@Value("${resolveflow.user-media-dir:tmp/user-media}") String root) {
        this.root = Path.of(root).toAbsolutePath().normalize();
    }

    public String save(byte[] bytes) {
        if (bytes == null || bytes.length == 0 || bytes.length > 2 * 1024 * 1024) throw invalid();
        try (var input = ImageIO.createImageInputStream(new ByteArrayInputStream(bytes))) {
            var readers = ImageIO.getImageReaders(input);
            if (!readers.hasNext()) throw invalid();
            var reader = readers.next();
            try {
                reader.setInput(input, true, true);
                String format = reader.getFormatName();
                int w = reader.getWidth(0), h = reader.getHeight(0);
                if (!(format.equalsIgnoreCase("png") || format.equalsIgnoreCase("jpeg"))
                        || w < 1
                        || h < 1
                        || w > 4096
                        || h > 4096) throw invalid();
                var image = reader.read(0);
                var output = new BufferedImage(256, 256, BufferedImage.TYPE_INT_ARGB);
                var graphics = output.createGraphics();
                try {
                    graphics.setRenderingHint(
                            RenderingHints.KEY_INTERPOLATION, RenderingHints.VALUE_INTERPOLATION_BICUBIC);
                    int side = Math.min(w, h);
                    graphics.drawImage(
                            image,
                            0,
                            0,
                            256,
                            256,
                            (w - side) / 2,
                            (h - side) / 2,
                            (w + side) / 2,
                            (h + side) / 2,
                            null);
                } finally {
                    graphics.dispose();
                }
                Files.createDirectories(root);
                String id = UUID.randomUUID().toString();
                ImageIO.write(output, "png", path(id).toFile());
                return id;
            } finally {
                reader.dispose();
            }
        } catch (Refused e) {
            throw e;
        } catch (java.io.IOException e) {
            throw new Refused(400, "INVALID_IMAGE", "图片无法读取，请选择PNG或JPEG图片");
        }
    }

    private Path path(String id) {
        if (id == null || !id.matches("[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}")) throw invalid();
        return root.resolve(id + ".png");
    }

    public byte[] read(String id) {
        try {
            return Files.readAllBytes(path(id));
        } catch (java.io.IOException e) {
            throw new Refused(404, "NOT_FOUND", "头像不存在");
        }
    }

    public void discard(String id) {
        try {
            Files.deleteIfExists(path(id));
        } catch (java.io.IOException ignored) {
            /* orphan may be collected later */
        }
    }

    private static Refused invalid() {
        return new Refused(400, "INVALID_IMAGE", "请选择2MB以内、尺寸不超过4096像素的PNG或JPEG图片");
    }
}
